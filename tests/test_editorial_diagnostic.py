import json
import unittest
from uuid import uuid4

import httpx
from scripts.diagnose_editorial_run import diagnose


class DiagnosticTests(unittest.TestCase):
    def test_read_only_diagnosis_identifies_truncation_without_raw_contents(self):
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.path.endswith("/history"):
                return httpx.Response(200, json={"steps": [{"raw_response": "private prompt or secret",
                    "response_metadata": {"finish_reason": "length"}, "error_code": "output_incomplete"}]})
            return httpx.Response(200, json={"brief": {"topic": "private topic"}, "status": "failed", "error_code": "output_incomplete"})
        report = diagnose("http://127.0.0.1:8000", uuid4(), "x" * 32,
                          httpx.Client(transport=httpx.MockTransport(handler)))
        self.assertEqual(report["steps"][0]["finish_reason"], "length")
        self.assertFalse(report["steps"][0]["schema_valid"])
        self.assertTrue(all(request.method == "GET" for request in calls))
        self.assertNotIn("private", json.dumps(report))
        self.assertNotIn("x" * 32, json.dumps(report))

    def test_external_endpoint_is_rejected_before_network(self):
        with self.assertRaises(ValueError):
            diagnose("https://remote.test", uuid4(), "x" * 32)
