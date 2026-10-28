"""Voice, video and subtitle production from an approved 75-second storyboard.

Framework-free use cases: SQL, storage, Piper, FFmpeg and telemetry are injected
ports. No HTTP, no implicit retry and no overwrite of a ready media.
"""
import json
from pathlib import Path
import tempfile
import time
from uuid import UUID

from anyio.to_thread import run_sync
from functools import partial

KINDS = {"voice": ".wav", "video": ".mp4", "subtitles": ".srt"}


class ProductionMediaError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ProductionMediaCapacity:
    def __init__(self):
        self._busy = False

    def acquire(self, blocking=False):
        if self._busy:
            return False
        self._busy = True
        return True

    def release(self):
        self._busy = False


def offload(function, *args, **kwargs):
    return run_sync(partial(function, *args, **kwargs))


def _no_telemetry(**_kwargs):
    return None


def _private_directory(config):
    root = Path(config.media_directory) if config.media_directory else Path(tempfile.gettempdir())
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ProductionMediaError("production_media_directory_invalid")
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ProductionMediaError("production_media_directory_invalid")
    return root


class GenerateVoice:
    def __init__(self, repository, storage, synthesize, capacity, config):
        self.repository, self.storage = repository, storage
        self.synthesize, self.capacity = synthesize, capacity
        self.config = config

    async def execute(self, identity, run_id):
        plan = await offload(self.repository.plan, identity, run_id)
        if not plan.get("approved"):
            raise ProductionMediaError("approval_required")
        if plan.get("duration_seconds") != 75 or not plan.get("scenes"):
            raise ProductionMediaError("storyboard_duration_invalid")
        if not self.config.voice_configured():
            raise ProductionMediaError("voice_provider_unconfigured")
        if not self.capacity.acquire(blocking=False):
            raise ProductionMediaError("media_capacity_busy")
        try:
            reservation = await offload(self.repository.reserve, identity, run_id, "voice",
                                        plan["scenario_id"])
            return await offload(self._run, identity, run_id, plan, reservation)
        finally:
            self.capacity.release()

    def _run(self, identity, run_id, plan, reservation):
        with tempfile.TemporaryDirectory(prefix="arvor-voice-",
                                         dir=_private_directory(self.config)) as work:
            destination = Path(work) / "voice.wav"
            try:
                result = self.synthesize(
                    plan["scenes"], self.config.piper_model, destination,
                    piper=self.config.piper_bin, ffmpeg=self.config.ffmpeg_bin,
                    tenant=identity.tenant, story_id=run_id)
                reference = self.storage.save(destination, identity.tenant, run_id,
                                              reservation["asset_id"], "voice")
            except ProductionMediaError:
                raise
            except Exception as error:  # noqa: BLE001 - fixed codes only
                code = (str(error) if str(error).startswith(("voice_", "tts_", "piper_"))
                        else "voice_generation_failed")
                self.repository.fail(identity, run_id, "voice",
                                     scenario_id=plan["scenario_id"], error_code=code)
                raise ProductionMediaError(code) from None
        return self.repository.complete(
            identity, run_id, "voice", scenario_id=plan["scenario_id"],
            storage=reference, sha256=reference.get("sha256"),
            byte_count=reference.get("size"), duration_seconds=result["duration_seconds"])


class GenerateVideo:
    def __init__(self, repository, storage, render, capacity, config, telemetry=None):
        self.repository, self.storage = repository, storage
        self.render, self.capacity = render, capacity
        self.config, self.telemetry = config, telemetry or _no_telemetry

    async def execute(self, identity, run_id):
        plan = await offload(self.repository.plan, identity, run_id)
        if not plan.get("approved"):
            raise ProductionMediaError("approval_required")
        if not plan.get("ready_for_video"):
            raise ProductionMediaError("media_incomplete")
        if not self.config.video_configured():
            raise ProductionMediaError("video_provider_unconfigured")
        if not self.capacity.acquire(blocking=False):
            raise ProductionMediaError("media_capacity_busy")
        try:
            inputs = await offload(self.repository.inputs, identity, run_id, "video")
            reservation = await offload(self.repository.reserve, identity, run_id, "video",
                                        plan["scenario_id"])
            return await offload(self._run, identity, run_id, inputs, reservation)
        finally:
            self.capacity.release()

    def _run(self, identity, run_id, inputs, reservation):
        tenant, scenario_id = identity.tenant, inputs["scenario_id"]
        encoded = None
        try:
            with tempfile.TemporaryDirectory(prefix="arvor-video-",
                                             dir=_private_directory(self.config)) as work:
                work = Path(work)
                scenes = []
                for index, (scene, image) in enumerate(zip(inputs["scenes"], inputs["images"]), 1):
                    if not image or not image.get("storage"):
                        raise ProductionMediaError("media_incomplete")
                    name = f"scene-{index}.png"
                    self.storage.load(image["storage"], work / name, tenant, run_id,
                                      UUID(image["scene_id"]), "image")
                    scenes.append({"image": name,
                                   "duration_seconds": scene["duration_seconds"],
                                   "narration": scene["narration"]})
                voice = inputs.get("voice") or {}
                if not voice.get("storage"):
                    raise ProductionMediaError("media_incomplete")
                self.storage.load(voice["storage"], work / "voice.wav", tenant, run_id,
                                  UUID(voice["asset_id"]), "voice")
                manifest = {"schema_version": 1, "approved": True, "voice": "voice.wav",
                            "scenes": scenes,
                            "preproduction": {"run_id": str(run_id)}}
                manifest_path = work / "production.json"
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False),
                                         encoding="utf-8")
                started = time.monotonic()
                receipt = self.render(manifest_path, work / "export", arvor_75=True,
                                      telemetry=lambda _receipt: None)
                encoded = round(time.monotonic() - started, 3)
                video = self.storage.save(work / "export" / "episode.mp4", tenant, run_id,
                                          reservation["asset_id"], "video")
                subtitles = self.storage.save(work / "export" / "narration.srt", tenant,
                                              run_id, reservation["subtitles_id"],
                                              "subtitles")
                result = self.repository.complete(
                    identity, run_id, "video", scenario_id=scenario_id, storage=video,
                    sha256=video.get("sha256"), byte_count=video.get("size"),
                    duration_seconds=receipt["duration_seconds"],
                    extra_storage={"subtitles": subtitles})
        except ProductionMediaError:
            self.repository.fail(identity, run_id, "video", scenario_id=scenario_id,
                                 error_code="video_render_failed")
            raise
        except Exception:  # noqa: BLE001 - fixed codes only
            self.repository.fail(identity, run_id, "video", scenario_id=scenario_id,
                                 error_code="video_render_failed")
            raise ProductionMediaError("video_render_failed") from None
        self.telemetry(tenant=tenant, story_id=run_id, asset_id=reservation["asset_id"],
                       scene_count=len(scenes), target_seconds=75,
                       real_seconds=receipt["duration_seconds"], status="exported",
                       video_sha256=video.get("sha256"), byte_count=video.get("size"),
                       encode_seconds=encoded, ffmpeg_version=receipt.get("ffmpeg_version"),
                       audio=True, resolution="720x1280", fps=24)
        return result


class ReadProductionMedia:
    def __init__(self, repository, storage):
        self.repository, self.storage = repository, storage

    async def plan(self, identity, run_id):
        return await offload(self.repository.plan, identity, run_id)

    async def read(self, identity, run_id, media_id):
        reference = await offload(self.repository.reference, identity, run_id, media_id)
        kind = reference["kind"]
        if kind not in KINDS:
            raise ProductionMediaError("media_kind_invalid")
        directory = tempfile.TemporaryDirectory(prefix="arvor-stream-")
        destination = Path(directory.name) / ("media" + KINDS[kind])
        try:
            await offload(self.storage.load, reference["storage"], destination,
                          identity.tenant, run_id, media_id, kind)
        except Exception:
            directory.cleanup()
            raise ProductionMediaError("media_storage_unavailable") from None
        return {"path": destination, "kind": kind, "directory": directory,
                "sha256": reference.get("sha256"), "size": reference.get("size")}


def download_name(run_id, kind):
    stem = {"voice": "voix", "video": "video-75s", "subtitles": "sous-titres"}[kind]
    return f"arvor-{stem}-{str(run_id)[:8]}{KINDS[kind]}"
