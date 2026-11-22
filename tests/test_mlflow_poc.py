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
            "model": "DO_NOT_EXPORT_MODEL_SECRET", "duration_seconds": 0.23,
            "prompt": "DO_NOT_EXPORT_PROMPT",
            "response": "DO_NOT_EXPORT_ANSWER",
            "finish_reason": "stop",
            "usage": {"total_tokens": 23, "secret": "DO_NOT_EXPORT_TOKEN"},
        })
        encoded = json.dumps(result)
        for sensitive in ("DO_NOT_EXPORT_PROMPT", "DO_NOT_EXPORT_ANSWER",
                          "DO_NOT_EXPORT_TOKEN", "DO_NOT_EXPORT_MODEL_SECRET"):
            self.assertNotIn(sensitive, encoded)
        self.assertEqual(result["provider_adapter"], "llama.cpp-qwen")
        self.assertNotIn("model", result)
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



class TestInstrumentedCall(unittest.TestCase):
    def test_single_call_emits_redacted_trace(self):
        import asyncio
        import sys
        import types
        from contextlib import nullcontext
        from types import SimpleNamespace
        from scripts.poc_mlflow_qwen import execute_probe

        collected = {"calls": 0, "params": [], "metrics": [], "tags": []}

        class FakeSpan:
            def set_inputs(self, value):
                collected["inputs"] = value

            def set_outputs(self, value):
                collected["outputs"] = value

            def set_attribute(self, key, value):
                collected.setdefault("attrs", {})[key] = value

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        async def fake_generate(*args, **kwargs):
            collected["calls"] += 1
            return {
                "model": "qwen-local", "prompt": "SECRET_PROMPT",
                "response": "SECRET_RESPONSE", "duration_seconds": 0.12,
                "usage": {"total_tokens": 19},
                "finish_reason": "stop",
            }

        fake_llama = types.ModuleType("apps.api.llama_provider")
        fake_llama.ProviderError = type("ProviderError", (Exception,), {})
        fake_llama.generate_text = fake_generate
        fake_httpx = types.ModuleType("httpx")
        fake_httpx.AsyncClient = FakeClient
        fake_httpx.Timeout = lambda *args, **kwargs: None
        fake_entities = types.ModuleType("mlflow.entities")
        fake_entities.SpanType = SimpleNamespace(LLM="LLM")
        fake_mlflow = SimpleNamespace(
            set_tracking_uri=lambda uri: None,
            set_experiment=lambda name: None,
            start_run=lambda **kwargs: nullcontext(
                SimpleNamespace(info=SimpleNamespace(run_id="fake-run"))),
            start_span=lambda **kwargs: nullcontext(FakeSpan()),
            log_param=lambda key, value: collected["params"].append((key, value)),
            log_metric=lambda key, value: collected["metrics"].append((key, value)),
            set_tag=lambda key, value: collected["tags"].append((key, value)),
        )
        stubs = {
            "apps": types.ModuleType("apps"),
            "apps.api": types.ModuleType("apps.api"),
            "apps.api.llama_provider": fake_llama,
            "httpx": fake_httpx,
            "mlflow": types.ModuleType("mlflow"),
            "mlflow.entities": fake_entities,
        }
        with patch.dict(sys.modules, stubs):
            outcome = asyncio.run(execute_probe(
                fake_mlflow,
                tracking_uri="http://127.0.0.1:5000",
                model_url="http://127.0.0.1:8081",
            ))
        self.assertEqual(outcome["status"], "ok")
        self.assertEqual(collected["calls"], 1)
        serialized = json.dumps(collected)
        self.assertNotIn("SECRET_PROMPT", serialized)
        self.assertNotIn("SECRET_RESPONSE", serialized)
        self.assertEqual(collected["outputs"]["response_characters"], 15)


if __name__ == "__main__":
    unittest.main()
