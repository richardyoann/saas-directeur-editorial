import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5

from editorial.models import Brief
from editorial.store import PostgresStore, RunConflict, RunMissing
from editorial.worker_guard import WorkerOffline, WorkerAlreadyRunning, registered_worker, worker_online
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
        for name, parsed in zip(("analysis", "storyboard"), outputs(), strict=True):
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

    def test_queued_generation_requires_a_live_registered_worker(self):
        self.assertFalse(worker_online(self.store.database_url, self.tenant))
        with self.assertRaises(WorkerOffline):
            self.store.enqueue(self.tenant, self.actor, self.key, self.brief)
        with self.assertRaises(RunMissing):
            self.store.get(self.tenant, uuid5(self.tenant, "editorial-run:" + str(self.key)))
        with registered_worker(self.store.database_url, self.tenant):
            self.assertTrue(worker_online(self.store.database_url, self.tenant))
            with self.assertRaises(WorkerAlreadyRunning):
                with registered_worker(self.store.database_url, self.tenant):
                    pass
            queued, created = self.store.enqueue(self.tenant, self.actor, self.key, self.brief)
            self.assertTrue(created)
            self.assertEqual(queued["status"], "queued")
        self.assertFalse(worker_online(self.store.database_url, self.tenant))
        # The original idempotency key remains valid even during an outage.
        replay, created = self.store.enqueue(self.tenant, self.actor, self.key, self.brief)
        self.assertFalse(created)
        self.assertEqual(replay["id"], queued["id"])
        # But brand-new requests must not create unconsumable queue entries.
        with self.assertRaises(WorkerOffline):
            self.store.enqueue(self.tenant, self.actor, uuid4(), self.brief)

    def test_durable_queue_claims_are_idempotent_and_tenant_isolated(self):
        registration = registered_worker(self.store.database_url, self.tenant)
        registration.__enter__()
        self.addCleanup(registration.__exit__, None, None, None)

        queued, created = self.store.enqueue(self.tenant, self.actor, self.key, self.brief)
        self.assertTrue(created)
        self.assertEqual(queued["status"], "queued")
        duplicate, created = self.store.enqueue(self.tenant, self.actor, self.key, self.brief)
        self.assertFalse(created)
        self.assertEqual(queued, duplicate)
        self.assertIsNone(self.store.claim_queued(uuid4(), self.actor))
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(
                lambda _: self.store.claim_queued(self.tenant, self.actor), range(2)
            ))
        claimed = [r for r in claims if r is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["id"], queued["id"])
        self.assertEqual(claimed[0]["status"], "running")
        self.assertIsNone(self.store.claim_queued(self.tenant, self.actor))
        self.assertEqual(self.store.get(self.tenant, UUID(queued["id"]))["status"], "running")
        with self.store.connect() as conn:
            audit = conn.execute(
                "SELECT count(*) FROM po_audit WHERE correlation_id=%s",
                (UUID(queued["id"]),),
            ).fetchone()[0]
            outbox = conn.execute(
                "SELECT count(*) FROM po_outbox o JOIN po_audit a USING(event_id) "
                "WHERE a.correlation_id=%s", (UUID(queued["id"]),)
            ).fetchone()[0]
            self.assertEqual(audit, outbox)
            self.assertEqual(audit, 2)

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

    def test_explicit_interruption_is_atomic_idempotent_and_preserves_history(self):
        from datetime import datetime, timedelta, timezone

        run_id = self.run_start()
        self.store.begin_step(self.tenant, self.actor, run_id, "analysis", "prompt original")
        recent = self.store.reconcile_interrupted(self.tenant, self.actor, run_id)
        self.assertEqual(recent["status"], "running")

        old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE po_entity SET content=jsonb_set(content,'{current_step,started_at}',"
                "to_jsonb(%s::text)) WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s",
                (old, self.tenant, run_id),
            )
        with self.store.connect() as conn:
            before = conn.execute(
                "SELECT count(*) FROM po_audit WHERE correlation_id=%s", (run_id,)
            ).fetchone()[0]
        failed = self.store.reconcile_interrupted(self.tenant, self.actor, run_id)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error_code"], "run_interrupted")
        self.assertNotIn("current_step", failed)
        self.assertEqual(failed["steps"][-1]["status"], "failed")
        snapshot = self.store.history(self.tenant, run_id)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["prompt"], "prompt original")
        self.assertIsNone(snapshot[0]["raw_response"])
        self.assertEqual(snapshot[0]["error_code"], "run_interrupted")
        with self.store.connect() as conn:
            treatment = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s", (self.tenant, UUID(failed["steps"][-1]["treatment_id"]))
            ).fetchone()[0]
            self.assertEqual(treatment["status"], "failed")
            after = conn.execute("SELECT count(*) FROM po_audit WHERE correlation_id=%s", (run_id,)).fetchone()[0]
            self.assertGreater(after, before)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM po_outbox o JOIN po_audit a USING(event_id) "
                "WHERE a.correlation_id=%s", (run_id,)
            ).fetchone()[0], after)
        self.assertEqual(self.store.reconcile_interrupted(self.tenant, self.actor, run_id), failed)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM po_audit WHERE correlation_id=%s",
                                         (run_id,)).fetchone()[0], after)
        with self.assertRaises(RunConflict):
            self.store.save_step(self.tenant, self.actor, run_id, "analysis", "prompt original",
                                 {"response": "late"}, outputs()[0])

    def test_interruption_between_steps_and_isolation(self):
        from datetime import datetime, timedelta, timezone

        run_id = self.run_start()
        self.store.begin_step(self.tenant, self.actor, run_id, "analysis", "prompt")
        self.store.save_step(self.tenant, self.actor, run_id, "analysis", "prompt",
                             {"response": json.dumps(outputs()[0])}, outputs()[0])
        with self.assertRaises(RunMissing):
            self.store.reconcile_interrupted(uuid4(), self.actor, run_id)
        old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE po_entity SET content=jsonb_set(content,'{updated_at}',"
                "to_jsonb(%s::text)) WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s",
                (old, self.tenant, run_id),
            )
        run = self.store.reconcile_interrupted(self.tenant, self.actor, run_id)
        self.assertEqual(run["status"], "failed")
        self.assertEqual(len(run["steps"]), 1)
        self.assertEqual(len(self.store.history(self.tenant, run_id)), 1)

    def test_release_directory_sha_overrides_stale_config_in_persisted_run(self):
        import tempfile
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / (sha + "-123")
            (release / "editorial").mkdir(parents=True)
            with patch("editorial.store.__file__", str(release / "editorial/store.py")), patch.dict(
                    os.environ, {"EDITORIAL_CODE_VERSION": "b" * 40}):
                run_id = self.run_start()
            self.assertEqual(self.store.get(self.tenant, run_id)["code_version"], sha)

    def test_development_checkout_keeps_configured_code_version(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "source"
            (checkout / "editorial").mkdir(parents=True)
            with patch("editorial.store.__file__", str(checkout / "editorial/store.py")), patch.dict(
                    os.environ, {"EDITORIAL_CODE_VERSION": "configured-development"}):
                run_id = self.run_start()
            self.assertEqual(self.store.get(self.tenant, run_id)["code_version"], "configured-development")
