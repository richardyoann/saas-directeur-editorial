"""No-provider/no-MLflow-network checks for the isolated Qwen experiment."""
import json
import os
import unittest
from unittest.mock import patch

from scripts.poc_mlflow_qwen import main, private_url, safe_summary, token_metrics


class TestPrivateUrls(unittest.TestCase):
    def test_accepts_wsl_gateway_and_loopback(self):
        self.assertEqual(private_url("http://172.31.48.1:8081"), "http://172.31.48.1:8081")
        self.assertEqual(private_url("http://127.0.0.1:5000", loopback_only=True),
                         "http://127.0.0.1:5000")

    def test_telemetry_requires_loopback(self):
        with self.assertRaises(ValueError):
            private_url("http://172.31.48.1:5000", loopback_only=True)

    def test_rejects_public_or_credentialed_urls(self):
        for url in ("https://example.com:443", "http://8.8.8.8:5000",
                    "http://user:password@127.0.0.1:5000",
                    "http://localhost:5000/private", "http://localhost:5000?q=1",
                    "http://localhost:0", "http://127.0.0.1",
                    "http://0.0.0.0:5000"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                private_url(url)


class TestMetadataOnly(unittest.TestCase):
    def test_ignores_upstream_text_and_secret(self):
        result = safe_summary({
            "model": "qwen-local", "duration_seconds": 0.23,
            "prompt": "DO_NOT_EXPORT_PROMPT",
            "response": "DO_NOT_EXPORT_ANSWER",
            "finish_reason": "stop",
            "usage": {"total_tokens": 23, "secret": "DO_NOT_EXPORT_TOKEN"},
        })
        encoded = json.dumps(result)
        for sensitive in ("DO_NOT_EXPORT_PROMPT", "DO_NOT_EXPORT_ANSWER",
                          "DO_NOT_EXPORT_TOKEN"):
            self.assertNotIn(sensitive, encoded)
        self.assertEqual(result["response_characters"], len("DO_NOT_EXPORT_ANSWER"))
        self.assertEqual(result["tokens"]["total_tokens"], 23)

    def test_rejects_invalid_token_counts(self):
        self.assertEqual(token_metrics({"total_tokens": True, "prompt_tokens": -1,
                                        "completion_tokens": 12}),
                         {"completion_tokens": 12})


class TestExecutionGate(unittest.TestCase):
    def test_check_only_does_not_import_mlflow_or_generate(self):
        with patch.dict(os.environ, {
            "ARVOR_MLFLOW_TRACKING_URI": "http://127.0.0.1:5000",
            "LLM_BASE_URL": "http://172.31.48.1:8081",
        }):
            self.assertEqual(main([]), 0)

    def test_missing_model_configuration_fails_closed(self):
        with patch.dict(os.environ, {
            "ARVOR_MLFLOW_TRACKING_URI": "http://127.0.0.1:5000",
            "LLM_BASE_URL": "https://public.example.com:443",
        }):
            self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
