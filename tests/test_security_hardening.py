"""Regression tests for scoped security hardening; no production DB writes."""
import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from editorial.store import PostgresStore, RunMissing


class _FakeConnection:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.queries.append(query)
        return self

    def fetchone(self):
        return self.row


class DeletedOrWrongRunTests(unittest.TestCase):
    def test_both_step_methods_reject_non_run_entity(self):
        for method in ("begin_step", "save_step"):
            with self.subTest(method=method):
                db = _FakeConnection((1, {"type": "other", "steps": [],
                                          "status": "running"}))
                store = PostgresStore("not-used")
                with patch.object(store, "connect", return_value=db):
                    with self.assertRaises(RunMissing):
                        if method == "begin_step":
                            store.begin_step(uuid4(), uuid4(), uuid4(), "analysis", "prompt")
                        else:
                            store.save_step(uuid4(), uuid4(), uuid4(), "analysis",
                                            "prompt", {}, {})
                self.assertEqual(len(db.queries), 1)
                self.assertIn("AND NOT deleted FOR UPDATE", db.queries[0])

    def test_deleted_step_rows_cannot_be_selected(self):
        db = _FakeConnection(None)
        store = PostgresStore("not-used")
        with patch.object(store, "connect", return_value=db):
            with self.assertRaises(RunMissing):
                store.begin_step(uuid4(), uuid4(), uuid4(), "analysis", "prompt")
        self.assertIn("AND NOT deleted FOR UPDATE", db.queries[0])


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_is_cached_and_hides_dependency_details(self):
        mod = importlib.import_module("apps.api.main")
        class GoodClient:
            async def get(self, path, timeout):
                self.calls.append(path)
                return SimpleNamespace(status_code=200)
        client = GoodClient()
        client.calls = []
        with patch.dict(os.environ, {"PO_DATABASE_URL": "postgresql://invalid",
                                      "LLM_BASE_URL": "http://127.0.0.1:8081",
                                      "EDITORIAL_ASYNC_ENABLED": "false"}), patch.object(
                mod, "_database_ready", return_value=True) as db:
            mod._ready_cache.update(until=0, key=None, ok=False)
            first = await mod.ready(client)
            second = await mod.ready(client)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(len(client.calls), 1)
            db.assert_called_once()
            self.assertNotIn(b"postgresql", first.body)


if __name__ == "__main__":
    unittest.main()
