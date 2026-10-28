"""Framework-free voice/video use cases: no PostgreSQL, MinIO, Piper or FFmpeg."""
import hashlib
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from uuid import UUID, uuid4

from editorial.media.contracts import Identity, RunConflict
from production.media_pipeline import (
    GenerateVideo, GenerateVoice, ProductionMediaCapacity, ProductionMediaError,
    ReadProductionMedia, download_name,
)


def plan(**overrides):
    value = {"run_id": str(uuid4()), "approved": True, "scenario_id": str(uuid4()),
             "scene_count": 1, "duration_seconds": 75,
             "scenes": [{"scene_number": 1, "title": "Scène", "narration": "Bonjour.",
                         "duration_seconds": 75, "image_status": "ready"}],
             "media": {}, "ready_for_voice": True, "ready_for_video": True,
             "missing_images": []}
    value.update(overrides)
    return value


class FakeRepository:
    def __init__(self, current_plan, inputs=None):
        self.current_plan, self.inputs_result = current_plan, inputs
        self.reserved, self.completed, self.failures = [], [], []
        self.references = {}
        self.complete_result = {"media_id": str(uuid4()), "kind": "voice",
                                "sha256": "0" * 64, "size_bytes": 10,
                                "duration_seconds": 75}

    def plan(self, identity, run_id):
        return dict(self.current_plan)

    def inputs(self, identity, run_id, kind):
        return self.inputs_result

    def reserve(self, identity, run_id, kind, scenario_id):
        self.reserved.append((kind, scenario_id))
        return {"asset_id": uuid4(), "subtitles_id": uuid4(), "attempt": 1}

    def complete(self, identity, run_id, kind, **kwargs):
        self.completed.append((kind, kwargs))
        return dict(self.complete_result, kind=kind)

    def fail(self, identity, run_id, kind, **kwargs):
        self.failures.append((kind, kwargs))

    def reference(self, identity, run_id, media_id):
        return self.references[media_id]


class FakeStorage:
    def __init__(self):
        self.saved, self.loaded = [], []

    def save(self, path, tenant, run_id, asset_id, kind):
        data = Path(path).read_bytes()
        self.saved.append((kind, asset_id, data))
        return {"key": f"{kind}/{asset_id}", "kind": kind,
                "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}

    def load(self, reference, destination, tenant, run_id, asset_id, kind):
        self.loaded.append((kind, asset_id))
        data = b"\x89PNG\r\n\x1a\n" if kind == "image" else b"RIFF"
        Path(destination).write_bytes(data)
        return Path(destination)


class FakeConfig(SimpleNamespace):
    def voice_configured(self):
        return self.voice_ready

    def video_configured(self):
        return self.video_ready


def config(work, **overrides):
    values = {"media_directory": work, "piper_bin": "piper", "piper_model": "/voice.onnx",
              "ffmpeg_bin": "ffmpeg", "voice_ready": True, "video_ready": True}
    values.update(overrides)
    return FakeConfig(**values)


class OptionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.identity = Identity(uuid4(), uuid4())
        self.run_id = uuid4()

    async def test_voice_generates_once_and_records_ready_media(self):
        repository, storage = FakeRepository(plan()), FakeStorage()
        captured = {}

        def synthesize(scenes, model, destination, **kwargs):
            captured.update(scenes=scenes, model=model, kwargs=kwargs)
            Path(destination).write_bytes(b"RIFF" + b"\x00" * 8)
            return {"duration_seconds": 75, "voice_sha256": "a" * 64}

        service = GenerateVoice(repository, storage, synthesize, ProductionMediaCapacity(),
                                config(self.temp.name))
        result = await service.execute(self.identity, self.run_id)
        self.assertEqual(result["kind"], "voice")
        self.assertEqual(repository.reserved[0][0], "voice")
        self.assertEqual(repository.reserved[0][1], repository.current_plan["scenario_id"])
        self.assertEqual(repository.completed[0][0], "voice")
        self.assertEqual(repository.completed[0][1]["duration_seconds"], 75)
        self.assertEqual(storage.saved[0][0], "voice")
        self.assertEqual(captured["scenes"][0]["narration"], "Bonjour.")
        self.assertEqual(captured["kwargs"]["tenant"], self.identity.tenant)
        self.assertEqual(captured["kwargs"]["story_id"], self.run_id)
        self.assertFalse((Path(self.temp.name) / "voice.wav").exists())

    async def test_voice_requires_an_approved_75_second_storyboard(self):
        for current in (plan(approved=False), plan(duration_seconds=70),
                        plan(scenes=[])):
            with self.subTest(current=current):
                repository = FakeRepository(current)
                service = GenerateVoice(repository, FakeStorage(), lambda *a, **k: None,
                                        ProductionMediaCapacity(), config(self.temp.name))
                with self.assertRaises(ProductionMediaError) as caught:
                    await service.execute(self.identity, self.run_id)
                self.assertIn(caught.exception.code,
                              {"approval_required", "storyboard_duration_invalid"})
                self.assertEqual(repository.reserved, [])

    async def test_voice_provider_must_be_configured_before_reserving(self):
        repository = FakeRepository(plan())
        service = GenerateVoice(repository, FakeStorage(), lambda *a, **k: None,
                                ProductionMediaCapacity(),
                                config(self.temp.name, voice_ready=False))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "voice_provider_unconfigured")
        self.assertEqual(repository.reserved, [])

    async def test_voice_capacity_is_exclusive_and_always_released(self):
        capacity = ProductionMediaCapacity()
        self.assertTrue(capacity.acquire())
        repository = FakeRepository(plan())
        service = GenerateVoice(repository, FakeStorage(), lambda *a, **k: None,
                                capacity, config(self.temp.name))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "media_capacity_busy")
        self.assertEqual(repository.reserved, [])
        capacity.release()

        def synthesize(scenes, model, destination, **kwargs):
            Path(destination).write_bytes(b"RIFF")
            return {"duration_seconds": 75}

        service = GenerateVoice(FakeRepository(plan()), FakeStorage(), synthesize,
                                capacity, config(self.temp.name))
        await service.execute(self.identity, self.run_id)
        self.assertTrue(capacity.acquire())
        capacity.release()

        failing = GenerateVoice(
            FakeRepository(plan()), FakeStorage(),
            lambda *a, **k: (_ for _ in ()).throw(ValueError("tts_engine_failed")),
            capacity, config(self.temp.name))
        with self.assertRaises(ProductionMediaError):
            await failing.execute(self.identity, self.run_id)
        self.assertTrue(capacity.acquire())
        capacity.release()

    async def test_voice_failure_is_persisted_without_retry(self):
        repository = FakeRepository(plan())
        calls = []

        def synthesize(*args, **kwargs):
            calls.append(1)
            raise ValueError("tts_engine_failed")

        service = GenerateVoice(repository, FakeStorage(), synthesize,
                                ProductionMediaCapacity(), config(self.temp.name))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "tts_engine_failed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(repository.failures[0][1]["error_code"], "tts_engine_failed")
        self.assertEqual(repository.completed, [])

    async def test_voice_work_directory_is_validated_before_reserving(self):
        repository = FakeRepository(plan())
        service = GenerateVoice(repository, FakeStorage(), lambda *a, **k: None,
                                ProductionMediaCapacity(),
                                config(str(Path(self.temp.name) / "missing")))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "production_media_directory_invalid")
        self.assertEqual(repository.reserved, [])
        self.assertEqual(repository.failures, [])

    async def test_voice_domain_error_closes_the_reservation(self):
        repository = FakeRepository(plan())

        def synthesize(*args, **kwargs):
            raise ProductionMediaError("voice_duration_not_75")

        service = GenerateVoice(repository, FakeStorage(), synthesize,
                                ProductionMediaCapacity(), config(self.temp.name))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "voice_duration_not_75")
        self.assertEqual(repository.failures[0][1]["error_code"], "voice_duration_not_75")
        self.assertEqual(repository.completed, [])

    async def test_voice_publish_failure_closes_the_reservation(self):
        repository = FakeRepository(plan())

        def synthesize(scenes, model, destination, **kwargs):
            Path(destination).write_bytes(b"RIFF" + b"\x00" * 8)
            return {"duration_seconds": 75}

        def complete(*args, **kwargs):
            raise RunConflict()

        repository.complete = complete
        service = GenerateVoice(repository, FakeStorage(), synthesize,
                                ProductionMediaCapacity(), config(self.temp.name))
        with self.assertRaises(RunConflict):
            await service.execute(self.identity, self.run_id)
        self.assertEqual(repository.failures[0][1]["error_code"], "voice_generation_failed")

    async def test_video_requires_every_prerequisite(self):
        repository = FakeRepository(plan(ready_for_video=False))
        service = GenerateVideo(repository, FakeStorage(), lambda *a, **k: None,
                                ProductionMediaCapacity(), config(self.temp.name))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "media_incomplete")

    async def test_video_renders_uploads_and_reports_measurements(self):
        scenario_id = str(uuid4())
        inputs = {
            "scenario_id": scenario_id,
            "scenes": [{"scene_id": str(uuid4()), "duration_seconds": 75,
                        "narration": "Bonjour."}],
            "images": [{"asset_id": str(uuid4()), "scene_id": str(uuid4()),
                        "storage": "unused"}],
            "voice": {"asset_id": str(uuid4()), "storage": "unused"},
            "total_seconds": 75,
        }
        repository = FakeRepository(plan(scenario_id=scenario_id), inputs)
        storage = FakeStorage()
        telemetry, renders = [], []

        def render(manifest, destination, *, arvor_75=False, telemetry=None):
            renders.append({"manifest": Path(manifest).read_text(encoding="utf-8"),
                            "arvor_75": arvor_75, "telemetry": telemetry})
            Path(destination).mkdir(parents=True)
            (Path(destination) / "episode.mp4").write_bytes(b"mp4")
            (Path(destination) / "narration.srt").write_bytes(b"1\n")
            return {"duration_seconds": 75, "ffmpeg_version": "ffmpeg 8.0.1"}

        service = GenerateVideo(repository, storage, render, ProductionMediaCapacity(),
                                config(self.temp.name),
                                telemetry=lambda **kwargs: telemetry.append(kwargs))
        result = await service.execute(self.identity, self.run_id)
        self.assertEqual(result["kind"], "video")
        self.assertTrue(renders[0]["arvor_75"])
        self.assertTrue(callable(renders[0]["telemetry"]))
        self.assertEqual(repository.reserved[0][0], "video")
        completed = repository.completed[0][1]
        self.assertEqual(completed["duration_seconds"], 75)
        self.assertIn("subtitles", completed["extra_storage"])
        self.assertEqual([item[0] for item in storage.saved], ["video", "subtitles"])
        self.assertEqual(telemetry[0]["tenant"], self.identity.tenant)
        self.assertEqual(telemetry[0]["story_id"], self.run_id)
        self.assertEqual(telemetry[0]["target_seconds"], 75)
        self.assertTrue(telemetry[0]["audio"])

    async def test_video_render_failure_is_persisted_without_retry(self):
        inputs = {
            "scenario_id": str(uuid4()),
            "scenes": [{"scene_id": str(uuid4()), "duration_seconds": 75,
                        "narration": "Bonjour."}],
            "images": [{"asset_id": str(uuid4()), "scene_id": str(uuid4()),
                        "storage": "unused"}],
            "voice": {"asset_id": str(uuid4()), "storage": "unused"},
            "total_seconds": 75,
        }
        repository = FakeRepository(plan(scenario_id=inputs["scenario_id"]), inputs)

        def render(*args, **kwargs):
            raise ValueError("media_command_failed")

        service = GenerateVideo(repository, FakeStorage(), render,
                                ProductionMediaCapacity(), config(self.temp.name))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "video_render_failed")
        self.assertEqual(repository.failures[0][1]["error_code"], "video_render_failed")
        self.assertEqual(repository.completed, [])

    async def test_video_publish_failure_closes_the_reservation(self):
        inputs = {
            "scenario_id": str(uuid4()),
            "scenes": [{"scene_id": str(uuid4()), "duration_seconds": 75,
                        "narration": "Bonjour."}],
            "images": [{"asset_id": str(uuid4()), "scene_id": str(uuid4()),
                        "storage": "unused"}],
            "voice": {"asset_id": str(uuid4()), "storage": "unused"},
            "total_seconds": 75,
        }
        repository = FakeRepository(plan(scenario_id=inputs["scenario_id"]), inputs)

        def render(manifest, destination, *, arvor_75=False, telemetry=None):
            Path(destination).mkdir(parents=True)
            (Path(destination) / "episode.mp4").write_bytes(b"mp4")
            (Path(destination) / "narration.srt").write_bytes(b"1\n")
            return {"duration_seconds": 75}

        def complete(*args, **kwargs):
            raise RunConflict()

        repository.complete = complete
        service = GenerateVideo(repository, FakeStorage(), render,
                                ProductionMediaCapacity(), config(self.temp.name))
        with self.assertRaises(RunConflict):
            await service.execute(self.identity, self.run_id)
        self.assertEqual(repository.failures[0][1]["error_code"], "video_render_failed")

    async def test_telemetry_failure_never_breaks_a_published_video(self):
        inputs = {
            "scenario_id": str(uuid4()),
            "scenes": [{"scene_id": str(uuid4()), "duration_seconds": 75,
                        "narration": "Bonjour."}],
            "images": [{"asset_id": str(uuid4()), "scene_id": str(uuid4()),
                        "storage": "unused"}],
            "voice": {"asset_id": str(uuid4()), "storage": "unused"},
            "total_seconds": 75,
        }
        repository = FakeRepository(plan(scenario_id=inputs["scenario_id"]), inputs)

        def render(manifest, destination, *, arvor_75=False, telemetry=None):
            Path(destination).mkdir(parents=True)
            (Path(destination) / "episode.mp4").write_bytes(b"mp4")
            (Path(destination) / "narration.srt").write_bytes(b"1\n")
            return {"duration_seconds": 75}

        def telemetry(**kwargs):
            raise RuntimeError("tracker down")

        service = GenerateVideo(repository, FakeStorage(), render,
                                ProductionMediaCapacity(), config(self.temp.name),
                                telemetry=telemetry)
        result = await service.execute(self.identity, self.run_id)
        self.assertEqual(result["kind"], "video")
        self.assertEqual(repository.failures, [])

    async def test_read_materialises_a_private_temporary_copy(self):
        media_id, reference = uuid4(), {
            "kind": "voice", "storage": "unused", "sha256": "a" * 64, "size": 4}
        repository = FakeRepository(plan())
        repository.references[media_id] = reference
        service = ReadProductionMedia(repository, FakeStorage())
        result = await service.read(self.identity, self.run_id, media_id)
        self.addCleanup(result["directory"].cleanup)
        self.assertEqual(result["kind"], "voice")
        self.assertEqual(result["path"].read_bytes(), b"RIFF")
        self.assertEqual(download_name(self.run_id, "voice"),
                         f"arvor-voix-{str(self.run_id)[:8]}.wav")

    async def test_read_maps_a_storage_failure_to_a_bounded_error(self):
        media_id = uuid4()
        repository = FakeRepository(plan())
        repository.references[media_id] = {
            "kind": "video", "storage": "unused", "sha256": "a" * 64, "size": 4}

        class BrokenStorage:
            def load(self, *args, **kwargs):
                raise OSError("secret /home/example/path")

        service = ReadProductionMedia(repository, BrokenStorage())
        with self.assertRaises(ProductionMediaError) as caught:
            await service.read(self.identity, self.run_id, media_id)
        self.assertEqual(caught.exception.code, "media_storage_unavailable")
        self.assertNotIn("/home", str(caught.exception))

    async def test_read_rejects_unknown_kind_and_conflicts(self):
        media_id = uuid4()
        repository = FakeRepository(plan())
        repository.references[media_id] = {"kind": "manifest", "storage": "x",
                                           "sha256": "a" * 64, "size": 1}
        service = ReadProductionMedia(repository, FakeStorage())
        with self.assertRaises(ProductionMediaError) as caught:
            await service.read(self.identity, self.run_id, media_id)
        self.assertEqual(caught.exception.code, "media_kind_invalid")


class ContractTests(unittest.TestCase):
    def test_identity_is_required_and_uuid_typed(self):
        identity = Identity(uuid4(), uuid4())
        self.assertIsInstance(identity.tenant, UUID)
        self.assertIsInstance(identity.actor, UUID)

    def test_run_conflict_is_the_repository_contract(self):
        self.assertTrue(issubclass(RunConflict, Exception))


if __name__ == "__main__":
    unittest.main()
