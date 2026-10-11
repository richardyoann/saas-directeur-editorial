import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from editorial.models import Brief
from editorial.store import PostgresStore, RunConflict, RunMissing
from test_editorial import outputs


@unittest.skipUnless(os.getenv("PO_TEST_DATABASE_URL"), "dedicated PostgreSQL test target not configured")
class EditorialPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes":
            raise RuntimeError("test migration not authorized")
        cls.store = PostgresStore(os.environ["PO_TEST_DATABASE_URL"])
        with cls.store.connect() as conn:
            conn.execute(Path("pilotage/migration.sql").read_text())

    def setUp(self):
        self.tenant, self.actor, self.key = uuid4(), uuid4(), uuid4()
        self.brief = Brief(topic="Ys").model_dump()

    def run_start(self):
        run, created = self.store.start(self.tenant, self.actor, self.key, self.brief)
        self.assertTrue(created)
        return UUID(run["id"])

    def test_full_workflow_persists_exact_snapshots_and_audit_outbox(self):
        run_id = self.run_start()
        for name, parsed in zip(("analysis", "storyboard"), outputs()):
            prompt = "exact prompt " + name
            response = {"response": json.dumps(parsed), "model": "Qwen-test", "provider": "llama.cpp", "finish_reason": "stop", "usage": {"total_tokens": 50}, "duration_seconds": 0.1}
            self.store.begin_step(self.tenant, self.actor, run_id, name, prompt)
            run = self.store.save_step(self.tenant, self.actor, run_id, name, prompt, response, parsed)
        self.assertEqual(run["status"], "waiting_validation")
        self.assertEqual(len(run["scene_ids"]), 3)
        history = self.store.history(self.tenant, run_id)
        self.assertEqual(history[0]["prompt"], "exact prompt analysis")
        self.assertEqual(json.loads(history[1]["raw_response"]), outputs()[1])
        with self.store.connect() as conn:
            counts = conn.execute("SELECT (SELECT count(*) FROM po_audit WHERE correlation_id=%s),(SELECT count(*) FROM po_outbox o JOIN po_audit a USING(event_id) WHERE a.correlation_id=%s)", (run_id, run_id)).fetchone()
            self.assertGreater(counts[0], 10)
            self.assertEqual(counts[0], counts[1])
            self.assertEqual(conn.execute("SELECT count(*) FROM po_entity WHERE tenant_id=%s AND kind='scene'", (self.tenant,)).fetchone()[0], 3)
        cached, created = self.store.start(self.tenant, self.actor, self.key, self.brief)
        self.assertFalse(created)
        self.assertEqual(cached, run)

    def test_tenant_isolation_and_changed_brief_conflict(self):
        run_id = self.run_start()
        for method in (self.store.get, self.store.history):
            with self.assertRaises(RunMissing):
                method(uuid4(), run_id)
        with self.assertRaises(RunConflict):
            self.store.start(self.tenant, self.actor, self.key, self.brief | {"topic": "Autre"})

    def test_concurrent_start_makes_one_run(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.start(self.tenant, self.actor, self.key, self.brief), range(2)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(results[0][0]["id"], results[1][0]["id"])

    def test_failure_retains_raw_output_and_stops_run(self):
        run_id = self.run_start()
        self.store.begin_step(self.tenant, self.actor, run_id, "analysis", "prompt")
        run = self.store.save_step(self.tenant, self.actor, run_id, "analysis", "prompt", {"response": "invalid output"}, None, "invalid_structured_output")
        self.assertEqual(run["status"], "failed")
        self.assertEqual(self.store.history(self.tenant, run_id)[0]["raw_response"], "invalid output")
        with self.assertRaises(RunConflict):
            self.store.begin_step(self.tenant, self.actor, run_id, "storyboard", "prompt")

    def test_failed_transaction_rolls_back_result_and_run_transition(self):
        run_id = self.run_start()
        self.store.begin_step(self.tenant, self.actor, run_id, "analysis", "prompt")
        original = self.store._write
        def fail(conn, *args, **kwargs):
            original(conn, *args, **kwargs)
            if args[3] == "result":
                raise RuntimeError("injected failure")
        with patch.object(self.store, "_write", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.store.save_step(self.tenant, self.actor, run_id, "analysis", "prompt", {"response": "text"}, outputs()[0])
        self.assertEqual(self.store.get(self.tenant, run_id)["steps"], [])
        self.assertEqual(self.store.history(self.tenant, run_id), [])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM po_audit WHERE correlation_id=%s", (run_id,)).fetchone()[0], 4)
