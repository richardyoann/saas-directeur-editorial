"""Isolation of PC deployment: production must never receive test-run writes."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy_local as d


SHA = "a" * 40
TEST_URL = "postgresql://po_test:ephemeral_ci_only@127.0.0.1:54323/po_test"
BUSINESS_URL = "postgresql://editor:private_password@127.0.0.1:5432/editorial_prod"


class IsolatedPCReleaseTests(unittest.TestCase):
    def test_only_dedicated_ephemeral_database_is_accepted(self):
        self.assertEqual(d.disposable_database_url(TEST_URL, BUSINESS_URL), TEST_URL)
        invalid = [
            BUSINESS_URL, "postgresql://po_test:ephemeral_ci_only@server/po_test",
            "postgresql://po_test:wrong@127.0.0.1:54323/po_test",
            "postgresql://po_test:ephemeral_ci_only@169.254.169.254:54323/po_test",
            "postgresql://po_test:ephemeral_ci_only@127.0.0.1:54323/real",
            "postgresql://po_test:ephemeral_ci_only@127.0.0.1:54323/po_test?sslmode=disable",
            "postgresql://po_test:ephemeral_ci_only@127.0.0.1/po_test",
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate.split("@")[-1]), self.assertRaises(ValueError):
                d.disposable_database_url(candidate, BUSINESS_URL)
        with self.assertRaises(ValueError):
            d.disposable_database_url(TEST_URL, TEST_URL)
        # Same physical DB must fail even when usernames differ.
        with self.assertRaises(ValueError):
            d.disposable_database_url(TEST_URL,
                "postgresql://another:pass@localhost:54323/po_test")

    def test_candidate_process_overrides_database_and_actor_without_editing_parent(self):
        settings = {"PO_DATABASE_URL": BUSINESS_URL}
        with patch.dict(os.environ, {"PO_DATABASE_URL": BUSINESS_URL,
                                     "EDITORIAL_TENANT_ID": "user-tenant",
                                     "EDITORIAL_ASYNC_ENABLED": "true"}):
            result = d.candidate_test_environment(TEST_URL, settings)
            self.assertEqual(result["PO_DATABASE_URL"], TEST_URL)
            self.assertNotEqual(result["EDITORIAL_TENANT_ID"], "user-tenant")
            self.assertEqual(result["EDITORIAL_ASYNC_ENABLED"], "false")
            self.assertEqual(os.environ["PO_DATABASE_URL"], BUSINESS_URL)
            self.assertEqual(os.environ["EDITORIAL_TENANT_ID"], "user-tenant")
            self.assertNotEqual(result["EDITORIAL_TENANT_ID"],
                                result["EDITORIAL_ACTOR_ID"])

    def test_disposable_schema_can_only_connect_after_validation(self):
        with patch("psycopg.connect") as connect:
            with self.assertRaises(ValueError):
                d.prepare_disposable_editorial_db(BUSINESS_URL, BUSINESS_URL)
            connect.assert_not_called()
            d.prepare_disposable_editorial_db(TEST_URL, BUSINESS_URL)
            self.assertEqual(connect.call_args.args[0], TEST_URL)
            conn = connect.return_value.__enter__.return_value
            sql = conn.execute.call_args.args[0]
            self.assertIn("CREATE TABLE", sql)

    def test_repository_approval_requires_both_gate_and_exact_sha(self):
        with patch.dict(os.environ, {
            "LOCAL_PC_ENABLED": "true", "LOCAL_PC_APPROVED_SHA": SHA
        }):
            d.verify_approved_sha(SHA)
            with self.assertRaises(RuntimeError):
                d.verify_approved_sha("b" * 40)
        with patch.dict(os.environ, {
            "LOCAL_PC_ENABLED": "false", "LOCAL_PC_APPROVED_SHA": SHA
        }):
            with self.assertRaises(RuntimeError):
                d.verify_approved_sha(SHA)
        with patch.dict(os.environ, {
            "LOCAL_PC_ENABLED": "true", "LOCAL_PC_APPROVED_SHA": ""
        }):
            with self.assertRaises(RuntimeError):
                d.verify_approved_sha(SHA)

    def test_main_sha_requires_successful_regression_and_security_audit(self):
        success = json.dumps({"workflow_runs": [{
            "head_sha": SHA, "head_branch": "main",
            "event": "push", "status": "completed", "conclusion": "success"
        }]}).encode()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy"}), \
             patch("deploy_local.urllib.request.urlopen",
                   side_effect=[io.BytesIO(success), io.BytesIO(success)]) as get:
            d.assert_ci_success(SHA)
            self.assertEqual(get.call_count, 2)
            self.assertIn("regression.yml", get.call_args_list[0].args[0].full_url)
            self.assertIn("security-deps.yml", get.call_args_list[1].args[0].full_url)
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy"}), \
             patch("deploy_local.urllib.request.urlopen",
                   return_value=io.BytesIO(json.dumps({"workflow_runs": [{
                       "head_sha": "b" * 40, "head_branch": "main",
                       "event": "push", "status": "completed", "conclusion": "success",
                   }]}).encode())):
            with self.assertRaises(RuntimeError):
                d.assert_ci_success(SHA)

    def test_active_runtime_and_editorial_probes_make_only_get_requests(self):
        seen = []
        def handler(request):
            seen.append((request.method, request.url.path, request.url.query))
            self.assertEqual(request.method, "GET")
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/ready":
                return httpx.Response(200, json={"ready": True})
            if request.url.path == "/editorial/runs":
                return (httpx.Response(200, json={"runs": []}) if
                        request.headers.get("authorization") else httpx.Response(401))
            return httpx.Response(404)
        actual_client = httpx.Client
        def client_factory(*args, **kwargs):
            return actual_client(transport=httpx.MockTransport(handler))
        with patch("httpx.Client", side_effect=client_factory):
            d.check_runtime_readonly("http://127.0.0.1:8000")
            d.check_readonly_editorial("http://127.0.0.1:8000", "x" * 40)
        self.assertEqual([x[1] for x in seen],
                         ["/health", "/ready", "/editorial/runs", "/editorial/runs"])

    def test_github_job_requires_explicit_sha_even_on_manual_dispatch(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/local-delivery.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("vars.LOCAL_PC_ENABLED == 'true'", workflow)
        self.assertIn("vars.LOCAL_PC_APPROVED_SHA", workflow)
        self.assertIn("inputs.approved_sha == github.sha", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn('[[ "$APPROVED_SHA" == "$EXPECTED_SHA" ]]', workflow)
        self.assertLess(workflow.index("name: Enforce exact SHA approval"),
                        workflow.index("name: Prepare test dependencies and disposable DB"))

    def test_deployment_never_calls_real_editorial_generator_on_activated_release(self):
        import inspect
        body = inspect.getsource(d.deploy)
        # Exactly one generated editorial flow, on the isolated candidate.
        self.assertEqual(body.count("idempotency_key=business_key"), 1)
        self.assertIn("env=candidate_env", body)
        self.assertIn("prepare_disposable_editorial_db(", body)
        self.assertIn('command([python, "scripts/run_regression.py"], candidate, quiet=False, env=candidate_env)', body)
        self.assertIn("check_readonly_editorial(url, editorial_token)", body)
        self.assertIn("check_runtime_readonly(url)", body)
        self.assertNotIn("check(url)\n", body)
        self.assertLess(body.index("verify_approved_sha(sha)"),
                        body.index("root.mkdir("))


if __name__ == "__main__":
    unittest.main()
