"""Offline tests of OpenCode telemetry isolation."""
import io
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from scripts.mlflow_opencode_bridge import summarize, publish

class BridgeTests(unittest.TestCase):
    def test_content_never_leaves_counters(self):
        secret = "PRIVATE_PROMPT_SECRET"
        events = [
            {"type": "text", "part": {"text": secret}},
            {"type": "tool_use", "input": {"token": secret}},
            {"type": "step_finish"},
            {"type": "error", "message": secret},
        ]
        raw = b"".join(json.dumps(e).encode() + b"\n" for e in events)
        result = summarize(io.BytesIO(raw))
        self.assertEqual(result["events_total"], 4)
        self.assertEqual(result["tool_events"], 1)
        self.assertEqual(result["error_events"], 1)
        self.assertNotIn(secret, json.dumps(result))

    def test_malformed_and_empty_fail_closed(self):
        for raw in (b"", b"not json\n", b"[1,2]\n"):
            with self.assertRaises(ValueError):
                summarize(io.BytesIO(raw))

    def test_bounded_input(self):
        with self.assertRaises(ValueError):
            summarize(io.BytesIO(b"x" * 1048577 + b"\n"))

    def test_only_allowlisted_fields_are_published(self):
        collected = []
        fake = SimpleNamespace(
            set_tracking_uri=lambda value: None,
            set_experiment=lambda value: None,
            start_run=lambda **kw: nullcontext(SimpleNamespace(info=SimpleNamespace(run_id="f" * 32))),
            log_param=lambda k, v: collected.append((k, v)),
            set_tag=lambda k, v: collected.append((k, v)),
            log_metric=lambda k, v: collected.append((k, v)),
        )
        counts = summarize(io.BytesIO(b'{"type":"text","prompt":"PRIVATE_PROMPT_SECRET"}\n'))
        publish(fake, "http://127.0.0.1:5000", "a" * 40, 218, counts)
        self.assertNotIn("PRIVATE_PROMPT_SECRET", json.dumps(collected))
        self.assertIn(("merge_or_deploy_authorized", "false"), collected)

if __name__ == "__main__":
    unittest.main()
