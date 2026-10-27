"""Unit tests for privacy-safe, fail-open MLflow telemetry."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5

from infrastructure.observability import mlflow_tracker as tracker

SECRET_PROMPT = "PROMPT_METIER_SECRET_A_NE_JAMAIS_EXPORTER"
SECRET_ANSWER = "REPONSE_METIER_SECRET_A_NE_JAMAIS_EXPORTER"


def loopback_environment(**extra):
    values = {
        "ARVOR_MLFLOW_ENABLED": "true",
        "MLFLOW_TRACKING_URI": "http://127.0.0.1:5000",
        "MLFLOW_TRACKING_USERNAME": "arvor-admin",
        "MLFLOW_TRACKING_PASSWORD": "not-printed",
        "ARVOR_CODE_VERSION": "test-sha",
    }
    values.update(extra)
    return values


class FakeExperiment:
    experiment_id = "1"


class FakeRunInfo:
    run_id = "run-1"


class FakeRun:
    info = FakeRunInfo()


class FakeClient:
    def __init__(self):
        self.runs = []
        self.searches = 0

    def get_experiment_by_name(self, name):
        return FakeExperiment()

    def create_experiment(self, name):
        return "1"

    def search_runs(self, experiment_ids, filter_string=None, max_results=None):
        self.searches += 1
        return list(self.runs)

    def create_run(self, experiment_id, run_name=None, tags=None):
        self.runs.append(FakeRun())
        return FakeRun()

    def log_batch(self, run_id, metrics=None, params=None, tags=None):
        self.batch = {"metrics": metrics, "params": params, "tags": tags}

    def set_terminated(self, run_id, status=None):
        self.terminated = status

    def set_tag(self, run_id, key, value):
        self.tag = (key, value)


class FakeSpan:
    def set_inputs(self, inputs):
        self.inputs = inputs

    def set_outputs(self, outputs):
        self.outputs = outputs

    def set_attributes(self, attributes):
        self.attributes = attributes


class FakeMlflow(types.ModuleType):
    def __init__(self):
        super().__init__("mlflow")
        self.client = FakeClient()
        self.terminated = None
        self.entities = types.ModuleType("mlflow.entities")
        self.entities.Metric = lambda *args: args
        self.entities.Param = lambda *args: args
        self.entities.RunTag = lambda *args: args
        sys.modules["mlflow"] = self
        sys.modules["mlflow.entities"] = self.entities

    def MlflowClient(self):
        return self.client

    def set_tracking_uri(self, uri):
        self.uri = uri

    def start_run(self, run_id=None, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def start_span(self, name, inputs=None, **kwargs):
        self.span = FakeSpan()
        self.span.name, self.span.inputs = name, inputs
        outer = self

        class Context:
            def __enter__(self):
                return outer.span

            def __exit__(self, *exc):
                return False

        return Context()


class ConfigurationTests(unittest.TestCase):
    def test_loopback_only(self):
        for uri in ("http://127.0.0.1:5000", "http://localhost:5000",
                    "https://[::1]:5000"):
            with self.subTest(uri=uri):
                self.assertTrue(tracker.configured_uri(uri))
        for uri in ("http://172.31.48.1:5000", "http://8.8.8.8:5000",
                    "https://mlflow.example.com:5000",
                    "http://user:pass@127.0.0.1:5000", "http://127.0.0.1:5000/api",
                    "http://127.0.0.1:5000?x=1", "http://127.0.0.1"):
            with self.subTest(uri=uri), self.assertRaises(tracker.TrackerConfigurationError):
                tracker.configured_uri(uri)

    def test_disabled_by_default_never_imports_mlflow(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(tracker, "_import_mlflow",
                             side_effect=AssertionError("must not import")):
            self.assertEqual(tracker.record_scenario_step(
                tenant=uuid4(), story_id=uuid4(), step="analysis", prompt="x",
                response="y", status="success"), "disabled")

    def test_external_uri_disables_tracking_silently(self):
        with patch.dict(os.environ, {"ARVOR_MLFLOW_ENABLED": "true",
                                     "MLFLOW_TRACKING_URI": "http://8.8.8.8:5000"},
                        clear=True), patch.object(tracker, "_import_mlflow",
                                                  side_effect=AssertionError()):
            self.assertEqual(tracker.record_image(
                tenant=uuid4(), story_id=uuid4(), scene_id=uuid4(), prompt="x",
                status="ready"), "disabled")


class SanitisationTests(unittest.TestCase):
    def test_model_name_is_technical_and_bounded(self):
        self.assertEqual(tracker.sanitize_model(
            r"C:\Users\Admin\.cache\Qwen\qwen2.5-3b-instruct-q4_k_m.gguf"),
            "qwen2.5-3b-instruct-q4_k_m.gguf")
        self.assertEqual(tracker.sanitize_model("../../etc/passwd"), "passwd")
        self.assertEqual(tracker.sanitize_model("bad model name"), "unknown")
        self.assertEqual(tracker.sanitize_model(None), "unknown")
        self.assertEqual(tracker.sanitize_model("x" * 200), "unknown")

    def test_scenario_event_never_contains_prompt_or_answer(self):
        event = tracker.scenario_event(
            tenant=uuid4(), story_id=uuid4(), step="analysis",
            prompt=SECRET_PROMPT, response=SECRET_ANSWER, status="success",
            model="qwen2.5-3b", usage={"prompt_tokens": 12, "completion_tokens": 7,
                                       "total_tokens": 19},
            duration_seconds=1.25)
        serialised = json.dumps(event)
        self.assertNotIn(SECRET_PROMPT, serialised)
        self.assertNotIn(SECRET_ANSWER, serialised)
        self.assertEqual(event["metrics"]["prompt_chars"], len(SECRET_PROMPT))
        self.assertEqual(event["metrics"]["output_chars"], len(SECRET_ANSWER))
        self.assertEqual(event["metrics"]["total_tokens"], 19)
        self.assertEqual(event["tags"]["arvor_prompt_sha256"],
                         tracker.sha256_text(SECRET_PROMPT))
        self.assertNotIn(str(event["tags"]["arvor_story_id"]), ())
        UUID(event["event_id"])

    def test_image_event_hashes_storage_reference(self):
        event = tracker.image_event(
            tenant=uuid4(), story_id=uuid4(), scene_id=uuid4(), prompt="secret",
            status="ready", width=512, height=512, duration_seconds=4.2,
            png_sha256="a" * 64, byte_count=1024,
            storage_ref="tenant/run/image/id.png")
        serialised = json.dumps(event)
        self.assertNotIn("tenant/run/image", serialised)
        self.assertEqual(event["tags"]["arvor_storage_ref_sha256"],
                         tracker.sha256_text("tenant/run/image/id.png"))

    def test_validation_rejects_content_keys_and_bad_values(self):
        base = tracker.image_event(tenant=uuid4(), story_id=uuid4(),
                                   scene_id=uuid4(), prompt="p", status="ready")
        for mutation in (
            lambda e: e["params"].update(prompt="raw"),
            lambda e: e["metrics"].update(duration_seconds=float("nan")),
            lambda e: e["metrics"].update(duration_seconds=-1),
            lambda e: e["tags"].update(arvor_story_id="not-a-uuid"),
            lambda e: e.update(experiment="other"),
            lambda e: e.update(unknown="x"),
        ):
            candidate = json.loads(json.dumps(base))
            mutation(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                tracker._validate(candidate)

    def test_trace_rejects_free_form_business_content(self):
        event = tracker.image_event(
            tenant=uuid4(), story_id=uuid4(), scene_id=uuid4(), prompt="p",
            status="ready", width=512, height=512)
        tracker._validate(event)  # the builder's trace is allowed
        for section, key in (("inputs", "narration"), ("outputs", "content"),
                             ("attributes", "prompt")):
            candidate = json.loads(json.dumps(event))
            candidate["trace"][section][key] = SECRET_ANSWER
            with self.subTest(section=section, key=key):
                with self.assertRaises(ValueError):
                    tracker._validate(candidate)
        candidate = json.loads(json.dumps(event))
        candidate["trace"]["name"] = SECRET_PROMPT
        with self.assertRaises(ValueError):
            tracker._validate(candidate)

    def test_event_ids_are_deterministic(self):
        tenant, story = uuid4(), uuid4()
        first = tracker.scenario_event(tenant=tenant, story_id=story, step="analysis",
                                       prompt="same", response="a", status="success")
        second = tracker.scenario_event(tenant=tenant, story_id=story, step="analysis",
                                        prompt="same", response="other", status="success")
        third = tracker.scenario_event(tenant=tenant, story_id=story, step="analysis",
                                       prompt="changed", response="a", status="success")
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertNotEqual(first["event_id"], third["event_id"])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        tracker.reset()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(tracker.reset)
        self.config = {"uri": "http://127.0.0.1:5000", "spool": "",
                       "code_version": "test-sha"}

    def test_publish_is_idempotent(self):
        fake = FakeMlflow()
        event = tracker.scenario_event(
            tenant=uuid4(), story_id=uuid4(), step="analysis", prompt="p",
            response="r", status="success")
        self.assertTrue(tracker._publish(event, self.config, fake))
        self.assertTrue(tracker._publish(event, self.config, fake))
        self.assertEqual(len(fake.client.runs), 1)
        self.assertEqual(fake.client.terminated, "FINISHED")
        self.assertEqual(fake.span.name, "arvor.scenario.analysis")

    def test_publish_failure_returns_false_without_raising(self):
        class Broken:
            def set_tracking_uri(self, uri):
                raise RuntimeError("down")

        event = tracker.video_event(tenant=uuid4(), story_id=uuid4(),
                                    scene_count=3, target_seconds=75)
        self.assertFalse(tracker._publish(event, self.config, Broken()))

    def test_publish_never_mutates_environment_with_credentials(self):
        with patch.dict(os.environ, loopback_environment(), clear=True):
            before = dict(os.environ)
            fake = FakeMlflow()
            event = tracker.image_event(
                tenant=uuid4(), story_id=uuid4(), scene_id=uuid4(), prompt="p",
                status="ready", png_sha256="f" * 64)
            self.assertTrue(tracker._publish(event, self.config, fake))
            self.assertEqual(os.environ, before)

    def test_corrupt_spool_is_preserved_and_replay_does_not_raise(self):
        spool = Path(self.temp.name) / "pending.jsonl"
        spool.write_bytes(b"\xff\xfe\x00broken\n")
        os.chmod(spool, 0o600)
        sink = tracker._Sink({**self.config, "spool": str(spool)})
        with patch.dict(os.environ,
                        loopback_environment(ARVOR_MLFLOW_SPOOL=str(spool)),
                        clear=True):
            report = tracker.flush_spool()
            sink._replay()
        self.assertEqual(report["error"], "unreadable")
        self.assertTrue(spool.exists())
        self.assertEqual(spool.read_bytes(), b"\xff\xfe\x00broken\n")

    def test_spool_replay_is_idempotent_and_removes_file(self):
        spool = Path(self.temp.name) / "spool/pending.jsonl"
        config = {**self.config, "spool": str(spool)}
        sink = tracker._Sink(config)
        event = tracker.image_event(tenant=uuid4(), story_id=uuid4(),
                                    scene_id=uuid4(), prompt="p", status="ready",
                                    png_sha256="b" * 64)
        self.assertTrue(sink._spool(event))
        self.assertTrue(spool.is_file())
        self.assertEqual(os.stat(spool).st_mode & 0o777, 0o600)
        fake = FakeMlflow()
        environment = loopback_environment(ARVOR_MLFLOW_SPOOL=str(spool))
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(tracker, "_import_mlflow", return_value=fake):
            report = tracker.flush_spool()
        self.assertEqual(report["replayed"], 1)
        self.assertEqual(report["failed"], 0)
        self.assertFalse(spool.exists())
        self.assertEqual(len(fake.client.runs), 1)

    def test_full_queue_falls_back_to_spool(self):
        spool = Path(self.temp.name) / "pending.jsonl"
        config = {**self.config, "spool": str(spool)}
        sink = tracker._Sink(config)
        sink.start = lambda: None  # Simulate a stalled publisher.
        event = tracker.video_event(tenant=uuid4(), story_id=uuid4(),
                                    scene_count=1, target_seconds=75)
        for _ in range(tracker.MAX_QUEUE):
            self.assertEqual(sink.submit(event), "queued")
        self.assertEqual(sink.submit(event), "spooled")
        self.assertTrue(spool.exists())

    def test_idle_worker_replays_the_spool_once(self):
        spool = Path(self.temp.name) / "pending.jsonl"
        event = tracker.image_event(tenant=uuid4(), story_id=uuid4(),
                                    scene_id=uuid4(), prompt="p", status="ready",
                                    png_sha256="e" * 64)
        spool.write_text(json.dumps(event) + "\n", encoding="utf-8")
        os.chmod(spool, 0o600)
        fake = FakeMlflow()
        sink = tracker._Sink({**self.config, "spool": str(spool)})
        with patch.dict(os.environ, loopback_environment(ARVOR_MLFLOW_SPOOL=str(spool)),
                        clear=True), \
                patch.object(tracker, "_import_mlflow", return_value=fake):
            sink._replay()
        self.assertFalse(spool.exists())
        self.assertEqual(len(fake.client.runs), 1)

    def test_spool_file_never_contains_business_text(self):
        spool = Path(self.temp.name) / "pending.jsonl"
        sink = tracker._Sink({**self.config, "spool": str(spool)})
        event = tracker.scenario_event(
            tenant=uuid4(), story_id=uuid4(), step="analysis",
            prompt=SECRET_PROMPT, response=SECRET_ANSWER, status="success")
        self.assertTrue(sink._spool(event))
        raw = spool.read_text(encoding="utf-8")
        self.assertNotIn(SECRET_PROMPT, raw)
        self.assertNotIn(SECRET_ANSWER, raw)
        self.assertEqual(json.loads(raw)["event_id"], event["event_id"])

    def test_replay_preserves_event_appended_after_claim(self):
        spool = Path(self.temp.name) / "pending.jsonl"
        sink = tracker._Sink({**self.config, "spool": str(spool)})
        first = tracker.image_event(
            tenant=uuid4(), story_id=uuid4(), scene_id=uuid4(), prompt="p",
            status="ready", png_sha256="a" * 64)
        second = tracker.image_event(
            tenant=uuid4(), story_id=uuid4(), scene_id=uuid4(), prompt="q",
            status="ready", png_sha256="b" * 64)
        self.assertTrue(sink._spool(first))
        fake = FakeMlflow()
        original_publish = tracker._publish

        def publish_during_replay(event, config, mlflow_module=None):
            # Simulates the daemon appending while the claimed file is replayed.
            sink._spool(second)
            return original_publish(event, config, fake)

        with patch.dict(os.environ,
                        loopback_environment(ARVOR_MLFLOW_SPOOL=str(spool)),
                        clear=True), \
                patch.object(tracker, "_import_mlflow", return_value=fake), \
                patch.object(tracker, "_publish", side_effect=publish_during_replay):
            report = tracker.flush_spool()
        self.assertEqual(report["replayed"], 1)
        self.assertTrue(spool.exists())
        lines = spool.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["event_id"] for line in lines],
                         [second["event_id"]])

    def test_spool_is_bounded(self):
        spool = Path(self.temp.name) / "pending.jsonl"
        spool.write_text("x" * (tracker.MAX_SPOOL_BYTES + 1), encoding="utf-8")
        sink = tracker._Sink({**self.config, "spool": str(spool)})
        event = tracker.video_event(tenant=uuid4(), story_id=uuid4(),
                                    scene_count=1, target_seconds=75)
        self.assertFalse(sink._spool(event))

    def test_recording_never_raises_on_bad_input(self):
        with patch.dict(os.environ, loopback_environment(), clear=True):
            self.assertEqual(tracker.record_image(
                tenant="not-a-uuid", story_id=object(), scene_id=None,
                prompt=object(), status="ready"), "dropped")


if __name__ == "__main__":
    unittest.main()
