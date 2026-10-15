"""Contract, data minimization and failure paths of queue diagnostics."""
import contextlib
from datetime import datetime, timezone
from io import StringIO
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

import psycopg
from scripts import diagnose_editorial_queue as monitor


AT = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)


class QueueMonitoringTests(unittest.TestCase):
    def test_grouped_states_and_overdue_detection(self):
        result = monitor.assess([
            ("queued", 2, "2026-10-14T23:49:00+00:00"),
            ("running", 1, "2026-10-14T23:56:00Z"),
            ("failed", 3, "2026-10-10T00:00:00+00:00"),
            ("waiting_validation", 1, "2026-10-10T00:00:00+00:00"),
        ], reference=AT)
        self.assertEqual(result["status"], "alert")
        self.assertEqual(result["alerts"], ["queued_overdue"])
        self.assertEqual(result["total_runs"], 7)
        self.assertEqual(result["oldest_age_seconds"], {"queued": 660, "running": 240})
        self.assertEqual(result["counts"]["waiting_validation"], 1)

    def test_running_stale_requires_operator_not_replay(self):
        result = monitor.assess(
            [("running", 1, "2026-10-14T23:40:00+00:00")], reference=AT)
        self.assertEqual(result["alerts"], ["running_stale"])
        self.assertNotIn("run_id", json.dumps(result))

    def test_unknown_timestamp_and_untrusted_status_are_not_exposed(self):
        result = monitor.assess([
            ("queued", 1, "2026-10-14T23:40:00"),  # Missing timezone
            ("private-brief-or-untrusted-status", 2, "2026-10-01T00:00:00+00:00"),
            ("running", 1, "2026-10-15T00:02:00+00:00"),  # Clock skew
        ], reference=AT)
        self.assertEqual(result["alerts"], ["queued_age_unknown", "running_age_unknown"])
        self.assertEqual(result["counts"]["other"], 2)
        self.assertNotIn("private-brief", json.dumps(result))

    def test_empty_queue_is_a_healthy_snapshot_not_worker_readiness(self):
        result = monitor.assess([], reference=AT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["total_runs"], 0)
        self.assertIsNone(result["oldest_age_seconds"]["queued"])

    def test_db_query_is_tenant_scoped_and_transaction_read_only(self):
        tenant = UUID("11111111-1111-4111-8111-111111111111")
        with patch.object(monitor.psycopg, "connect") as connect:
            conn = connect.return_value.__enter__.return_value
            conn.execute.side_effect = [
                None,
                SimpleNamespace(fetchall=lambda: [("queued", 1, AT.isoformat())]),
            ]
            rows = monitor.read_rows("hidden-db-url", tenant)
        self.assertEqual(rows[0][0], "queued")
        self.assertEqual(conn.execute.call_args_list[0].args[0], "SET TRANSACTION READ ONLY")
        sql, params = conn.execute.call_args_list[1].args
        self.assertIn("tenant_id = %s", sql)
        self.assertIn("kind = 'treatment'", sql)
        self.assertIn("NOT deleted", sql)
        self.assertEqual(params, (tenant,))
        self.assertNotIn("SELECT content FROM", sql)
        self.assertNotIn("raw_response", sql)
        self.assertNotIn("prompt", sql.lower())

    def test_missing_configuration_fails_closed_without_secrets(self):
        out = StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            monitor, "load_dotenv"
        ), contextlib.redirect_stdout(out):
            code = monitor.main([])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.getvalue())["reason"], "configuration_missing")

    def test_database_failure_does_not_print_connection_url(self):
        out = StringIO()
        environment = {
            "PO_DATABASE_URL": "postgresql://secret:password@localhost/hidden",
            "EDITORIAL_TENANT_ID": "11111111-1111-4111-8111-111111111111",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
            monitor, "load_dotenv"
        ), patch.object(monitor, "read_rows",
                        side_effect=psycopg.OperationalError(environment["PO_DATABASE_URL"])), \
                contextlib.redirect_stdout(out):
            code = monitor.main([])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.getvalue())["reason"], "database_or_data_error")
        self.assertNotIn("password", out.getvalue())

    def test_threshold_arguments_cannot_be_disabled(self):
        with contextlib.redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as caught:
                monitor.main(["--running-seconds", "0"])
        self.assertEqual(caught.exception.code, 2)


@unittest.skipUnless(os.getenv("PO_TEST_DATABASE_URL"),
                     "dedicated PostgreSQL test target not configured")
class RealPostgresQueueMonitoringTests(unittest.TestCase):
    """Exercise the actual SQL, not only a mocked psycopg connection."""

    @classmethod
    def setUpClass(cls):
        if os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes":
            raise RuntimeError("Disposable PostgreSQL test migration not authorized")
        from pathlib import Path
        from editorial.store import PostgresStore
        cls.database_url = os.environ["PO_TEST_DATABASE_URL"]
        cls.store = PostgresStore(cls.database_url)
        with cls.store.connect() as conn:
            conn.execute(Path("pilotage/migration.sql").read_text())

    def test_actual_postgres_aggregates_and_isolates_tenant(self):
        from uuid import uuid4
        from editorial.models import Brief
        from editorial.worker_guard import registered_worker

        tenant, foreign_tenant, actor = uuid4(), uuid4(), uuid4()
        brief = Brief(topic="Ys").model_dump()
        running, _ = self.store.start(tenant, actor, uuid4(), brief)
        self.store.begin_step(tenant, actor, UUID(running["id"]),
                              "analysis", "test prompt - must stay private")
        with registered_worker(self.database_url, tenant):
            queued, created = self.store.enqueue(tenant, actor, uuid4(), brief)
            self.assertTrue(created)
            self.assertEqual(queued["status"], "queued")
        self.store.start(foreign_tenant, actor, uuid4(),
                         Brief(topic="Another tenant").model_dump())

        # SELECT executes on the real PostgreSQL 16 CI service, in a
        # read-only transaction and without fetching raw editorial content.
        rows = monitor.read_rows(self.database_url, tenant)
        result = monitor.assess(rows)
        self.assertEqual(result["total_runs"], 2)
        self.assertEqual(result["counts"]["running"], 1)
        self.assertEqual(result["counts"]["queued"], 1)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("test prompt - must stay private", json.dumps(result))
        self.assertNotIn("Another tenant", json.dumps(result))
        self.assertIsNotNone(result["oldest_age_seconds"]["running"])


if __name__ == "__main__":
    unittest.main()
