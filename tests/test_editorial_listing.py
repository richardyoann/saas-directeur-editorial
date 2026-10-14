"""PostgreSQL regression for tenant-scoped editorial run pagination."""
import os
import unittest
from pathlib import Path
from uuid import uuid4

from editorial.models import Brief
from editorial.store import PostgresStore, RunMissing


@unittest.skipUnless(os.getenv("PO_TEST_DATABASE_URL"), "dedicated PostgreSQL required")
class EditorialListingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes":
            raise RuntimeError("test schema migration not authorized")
        cls.store = PostgresStore(os.environ["PO_TEST_DATABASE_URL"])
        with cls.store.connect() as conn:
            conn.execute(Path("pilotage/migration.sql").read_text())

    def test_list_is_tenant_scoped_paginated_and_excludes_raw_data(self):
        tenant, actor, other = uuid4(), uuid4(), uuid4()
        ids = []
        for topic in ["Brocéliande", "Ys", "Ankou"]:
            run, _ = self.store.start(tenant, actor, uuid4(), Brief(topic=topic).model_dump())
            ids.append(run["id"])
        foreign, _ = self.store.start(other, actor, uuid4(), Brief(topic="Secret").model_dump())
        all_items = self.store.list_runs(tenant, 50)
        self.assertTrue(set(ids).issubset({item["id"] for item in all_items["runs"]}))
        self.assertNotIn(foreign["id"], {item["id"] for item in all_items["runs"]})
        self.assertTrue(all("request_hash" not in item and "steps" not in item for item in all_items["runs"]))
        first = self.store.list_runs(tenant, 2)
        self.assertEqual(len(first["runs"]), 2)
        self.assertIsNotNone(first["next_before"])
        second = self.store.list_runs(tenant, 2, __import__("uuid").UUID(first["next_before"]))
        self.assertFalse({x["id"] for x in first["runs"]} & {x["id"] for x in second["runs"]})
        with self.assertRaises(RunMissing):
            self.store.list_runs(tenant, 2, __import__("uuid").UUID(foreign["id"]))
