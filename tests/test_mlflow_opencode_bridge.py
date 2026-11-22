"""Offline tests for the OpenCode JSONL -> MLflow observability bridge."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.mlflow_opencode_bridge import (
    KEYS, MAX_BYTES, MAX_EVENTS, MAX_LINE, load_input, loopback_tracking_uri, main, publish, summarize,
)


SECRET = "PRIVATE_PROMPT_SECRET_DO_NOT_EXPORT"
SESSION = "session_secret_123"
TOOL_ARG = "tool_arg_secret"
TOOL_OUT = "tool_output_secret"


def jsonl(events):
    return b"".join(json.dumps(event).encode("utf-8") + b"\n" for event in events)


REPRESENTATIVE_EVENTS = [
    {"type": "step_start", "step": 1, "session": SESSION},
    {"type": "text", "part": {"text": SECRET}},
    {"type": "reasoning", "content": SECRET},
    {"type": "tool_use", "tool": "bash", "input": {"cmd": TOOL_ARG}},
    {"type": "tool_result", "output": TOOL_OUT},
    {"type": "tool.call", "name": "read", "arguments": {"path": TOOL_ARG}},
    {"type": "tool.result", "result": TOOL_OUT},
    {"type": "message.part.updated", "part": {"type": "text", "text": SECRET}},
    {"type": "error", "message": SECRET},
    {"type": "step_finish", "status": "ok"},
    {"type": "unknown_future_event", "payload": SECRET},
]


class SummarizeTests(unittest.TestCase):
    def test_content_never_leaves_counters(self):
        raw = jsonl(REPRESENTATIVE_EVENTS)
        result = summarize(io.BytesIO(raw))
        self.assertEqual(result["events_total"], 11)
        self.assertEqual(result["content_events"], 3)
        self.assertEqual(result["tool_events"], 4)
        self.assertEqual(result["error_events"], 1)
        self.assertEqual(result["step_events"], 2)
        self.assertEqual(result["other_events"], 1)
        encoded = json.dumps(result)
        for sensitive in (SECRET, SESSION, TOOL_ARG, TOOL_OUT):
            self.assertNotIn(sensitive, encoded)

    def test_malformed_empty_and_shape_fail_closed(self):
        for raw in (b"", b"not json\n", b"[1,2]\n", b'"string"\n'):
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(ValueError):
                    summarize(io.BytesIO(raw))

    def test_bounded_line_size(self):
        with self.assertRaises(ValueError):
            summarize(io.BytesIO(b"x" * (MAX_LINE + 1) + b"\n"))

    def test_bounded_total_size(self):
        line = (json.dumps({"type": "text"}) + "\n").encode()
        count = (MAX_BYTES // len(line)) + 2
        with self.assertRaises(ValueError):
            summarize(io.BytesIO(line * count))

    def test_bounded_event_count(self):
        line = b'{"type":"step_start"}\n'
        with self.assertRaises(ValueError):
            summarize(io.BytesIO(line * (MAX_EVENTS + 1)))

    def test_unknown_events_counted_as_other(self):
        result = summarize(io.BytesIO(jsonl([{"type": "mystery", "data": SECRET}])))
        self.assertEqual(result, {"events_total": 1, "content_events": 0, "tool_events": 0,
                                  "error_events": 0, "step_events": 0, "other_events": 1})


class InputSecurityTests(unittest.TestCase):
    def test_symlink_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "events.jsonl"
            target.write_bytes(jsonl([{"type": "text"}]))
            link = Path(tmp) / "link.jsonl"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                load_input(str(link))

    def test_regular_file_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_bytes(jsonl([{"type": "text"}, {"type": "step_finish"}]))
            os.chmod(path, 0o600)
            result = load_input(str(path))
            self.assertEqual(result["events_total"], 2)

    def test_oversize_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_bytes(b'{"type":"text"}\n')
            with mock.patch("scripts.mlflow_opencode_bridge.MAX_BYTES", 5):
                with self.assertRaises(ValueError):
                    load_input(str(path))


class LoopbackOnlyTests(unittest.TestCase):
    def test_accepts_loopback(self):
        self.assertEqual(loopback_tracking_uri("http://127.0.0.1:5000"), "http://127.0.0.1:5000")
        self.assertEqual(loopback_tracking_uri("http://localhost:5000/"), "http://localhost:5000")

    def test_rejects_non_loopback_or_invalid(self):
        for uri in ("https://127.0.0.1:5000", "http://172.31.48.1:5000",
                    "http://8.8.8.8:5000", "http://user:pass@127.0.0.1:5000",
                    "http://127.0.0.1:5000/api", "http://127.0.0.1:5000?q=1",
                    "http://0.0.0.0:5000", "file:///tmp/mlflow", ""):
            with self.subTest(uri=uri):
                with self.assertRaises(ValueError):
                    loopback_tracking_uri(uri)


class PublishTests(unittest.TestCase):
    def test_only_allowlisted_fields_are_published(self):
        collected = []
        fake = SimpleNamespace(
            set_tracking_uri=lambda value: collected.append(("uri", value)),
            set_experiment=lambda value: collected.append(("exp", value)),
            start_run=lambda **kw: nullcontext(SimpleNamespace(info=SimpleNamespace(run_id="f" * 32))),
            log_param=lambda k, v: collected.append(("param", k, v)),
            set_tag=lambda k, v: collected.append(("tag", k, v)),
            log_metric=lambda k, v: collected.append(("metric", k, v)),
        )
        counts = {k: 0 for k in KEYS}
        counts["events_total"] = 3
        publish(fake, "http://127.0.0.1:5000", "A" * 40, 218, counts)
        encoded = json.dumps(collected)
        for sensitive in (SECRET, SESSION, TOOL_ARG, TOOL_OUT):
            self.assertNotIn(sensitive, encoded)
        self.assertIn(("tag", "merge_or_deploy_authorized", "false"), collected)
        self.assertIn(("tag", "ci_gate", "false"), collected)
        self.assertIn(("tag", "commit_sha_verified", "false"), collected)
        self.assertIn(("param", "commit_sha_declared", "a" * 40), collected)
        for key in KEYS:
            self.assertIn(("metric", key, counts[key]), collected)


class MainTests(unittest.TestCase):
    def _run_main(self, argv, env=None, stdin_bytes=None, mlflow_module=None):
        old_stdin = sys.stdin
        try:
            if stdin_bytes is not None:
                sys.stdin = io.TextIOWrapper(io.BytesIO(stdin_bytes), encoding="utf-8")
            with mock.patch.dict(os.environ, env or {}, clear=False):
                if mlflow_module is None:
                    return main(argv)
                with mock.patch.dict(sys.modules, {"mlflow": mlflow_module}):
                    return main(argv)
        finally:
            sys.stdin = old_stdin

    def test_observed_only_without_execute(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = self._run_main(["--sha", "a" * 40, "--input", "-"], stdin_bytes=jsonl([{"type": "text"}]))
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "observed_only")
        self.assertEqual(payload["quality_gate"], "not_evaluated")

    def test_invalid_sha_rejected(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = self._run_main(["--sha", "bad", "--input", "-"], stdin_bytes=b"{}\n")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(buf.getvalue())["status"], "invalid_metadata")

    def test_non_loopback_mlflow_rejected(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = self._run_main(["--sha", "a" * 40, "--execute", "--input", "-"],
                                  env={"ARVOR_MLFLOW_TRACKING_URI": "http://8.8.8.8:5000"},
                                  stdin_bytes=jsonl([{"type": "text"}]))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(buf.getvalue())["status"], "invalid_private_configuration")

    def test_mlflow_outage_is_fail_open(self):
        broken = SimpleNamespace(set_tracking_uri=mock.Mock(side_effect=RuntimeError("down")))
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = self._run_main(["--sha", "a" * 40, "--execute", "--input", "-"],
                                  env={"ARVOR_MLFLOW_TRACKING_URI": "http://127.0.0.1:5000"},
                                  stdin_bytes=jsonl([{"type": "text"}]), mlflow_module=broken)
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "telemetry_unavailable")
        self.assertEqual(payload["quality_gate"], "not_evaluated")

    def test_execute_records_only_allowlisted_fields(self):
        collected = []
        fake = SimpleNamespace(
            set_tracking_uri=lambda v: collected.append(("uri", v)),
            set_experiment=lambda v: collected.append(("exp", v)),
            start_run=lambda **kw: nullcontext(SimpleNamespace(info=SimpleNamespace(run_id="r"))),
            log_param=lambda k, v: collected.append(("param", k, v)),
            set_tag=lambda k, v: collected.append(("tag", k, v)),
            log_metric=lambda k, v: collected.append(("metric", k, v)),
        )
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = self._run_main(["--sha", "b" * 40, "--pr", "218", "--execute", "--input", "-"],
                                  env={"ARVOR_MLFLOW_TRACKING_URI": "http://127.0.0.1:5000"},
                                  stdin_bytes=jsonl(REPRESENTATIVE_EVENTS), mlflow_module=fake)
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "recorded")
        encoded = json.dumps(collected) + json.dumps(payload)
        for sensitive in (SECRET, SESSION, TOOL_ARG, TOOL_OUT):
            self.assertNotIn(sensitive, encoded)


class WiringGuardTests(unittest.TestCase):
    def test_bridge_not_wired_into_ci_or_delivery(self):
        root = Path(__file__).resolve().parents[1]
        # CI/supervisor scripts must not reference this observer as a gate/authority.
        sensitive = [
            root / "scripts/arvor_local_ci.py",
            root / "scripts/arvor_ci_gate.py",
            root / "scripts/arvor_ci_host_supervisor.py",
            root / "scripts/arvor_ci_supervised_entrypoint.sh",
            root / "scripts/arvor_ci_trusted_unittest.py",
            root / ".github/workflows/chat-approved-delivery.yml",
        ]
        for path in sensitive:
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("mlflow_opencode_bridge", text, path.name)
                self.assertNotIn("opencode-jsonl-observation", text, path.name)


if __name__ == "__main__":
    unittest.main()
