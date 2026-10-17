"""Real PostgreSQL integration cases; ONLY dedicated disposable test DB."""
import copy
import json
import os
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from editorial.models import Brief, ReviewDecision
from editorial.store import PostgresStore, RunConflict, RunMissing
from production.crew import ROLES, MAX_SCORES
from production.store import ProductionStore
from test_editorial import outputs


@unittest.skipUnless(os.getenv("PO_TEST_DATABASE_URL"), "dedicated PostgreSQL test target not configured")
class ProductionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes":
            raise RuntimeError("test migration not authorized")
        cls.store = PostgresStore(os.environ["PO_TEST_DATABASE_URL"])
        with cls.store.connect() as conn:
            conn.execute(Path("pilotage/migration.sql").read_text())

    def setUp(self):
        self.tenant, self.actor = uuid4(), uuid4()
        self.production = ProductionStore(self.store)
        brief = Brief(topic="Le phare fictif", duration_seconds=75,
                      scene_count=5, genre="fiction")
        run, _ = self.store.start(self.tenant, self.actor, uuid4(), brief.model_dump())
        self.run_id = UUID(run["id"])
        analysis, board = outputs()
        board = copy.deepcopy(board)
        board["scenes"] = [dict(board["scenes"][0], duration_seconds=15) for _ in range(5)]
        for name, parsed in (("analysis", analysis), ("storyboard", board)):
            self.store.begin_step(self.tenant, self.actor, self.run_id, name, "synthetic test prompt")
            self.store.save_step(self.tenant, self.actor, self.run_id, name, "synthetic test prompt",
                                 {"response": json.dumps(parsed), "finish_reason": "stop"}, parsed)
        self.store.review(self.tenant, self.actor, self.run_id, "analysis",
                          ReviewDecision(action="accept", expected_revision=0))
        approved = self.store.review(self.tenant, self.actor, self.run_id, "storyboard",
                                     ReviewDecision(action="accept", expected_revision=1))
        self.assertEqual(approved["status"], "approved")

    def test_only_one_claim_per_version_tenant_and_durable_history(self):
        current, created = self.production.start(self.tenant, self.actor, self.run_id)
        self.assertTrue(created)
        again, created = self.production.start(self.tenant, self.actor, self.run_id)
        self.assertFalse(created)
        self.assertEqual(current["id"], again["id"])
        with self.assertRaises(RunMissing):
            self.production.get(uuid4(), self.run_id)
        claimed = self.production.claim(self.tenant, self.actor, self.run_id, 0)
        self.assertEqual(claimed["current_role"], "screenwriter")
        with self.assertRaises(RunConflict):
            self.production.claim(self.tenant, self.actor, self.run_id, 0)
        artifact = {"summary": "Test", "directions": ["Film"], "constraints_checked": ["75s"],
                    "handoff": "Direction artistique"}
        result = self.production.finish(self.tenant, self.actor, self.run_id,
                                        claimed["revision"], "screenwriter", artifact)
        self.assertEqual(result["phase"], "ready")
        self.assertEqual(result["next_roles"][0], "art_director")
        with self.assertRaises(RunConflict):
            self.production.finish(self.tenant, self.actor, self.run_id,
                                   claimed["revision"], "screenwriter", artifact)
        history = self.production.history(self.tenant, self.run_id)
        self.assertEqual(len(history["outputs"]), 1)
        self.assertEqual(history["outputs"][0]["role"], "screenwriter")
        with self.store.connect() as conn:
            counts = conn.execute(
                "SELECT (SELECT count(*) FROM po_audit WHERE correlation_id=%s),"
                "(SELECT count(*) FROM po_outbox o JOIN po_audit a USING(event_id) "
                "WHERE a.correlation_id=%s)", (self.run_id, self.run_id)
            ).fetchone()
            self.assertEqual(counts[0], counts[1])

    def test_critic_blocks_and_corrections_retain_prior_roles(self):
        self.production.start(self.tenant, self.actor, self.run_id)
        for role in ROLES:
            state = self.production.get(self.tenant, self.run_id)
            claimed = self.production.claim(self.tenant, self.actor, self.run_id, state["revision"])
            if role == "critic":
                output = {**MAX_SCORES, "narrative": 14,
                          "blocking_issues": ["Rupture de continuité entre les scènes."],
                          "observations": ["Corriger une incohérence visuelle clairement identifiable."],
                          "target_roles": ["cinematographer"]}
            else:
                output = {"summary": role, "directions": ["production"], "constraints_checked": ["75s"], "handoff": role}
            state = self.production.finish(self.tenant, self.actor, self.run_id,
                                           claimed["revision"], role, output)
        self.assertEqual(state["phase"], "changes_requested")
        self.assertFalse(state["quality"]["passed"])
        with self.assertRaises(RunConflict):
            self.production.request_correction(self.tenant, self.actor, self.run_id,
                                               state["revision"], "screenwriter")
        amended = self.production.request_correction(self.tenant, self.actor, self.run_id,
                                                      state["revision"], "cinematographer")
        self.assertEqual(amended["cycle"], 1)
        self.assertIn("screenwriter", amended["outputs"])
        self.assertNotIn("cinematographer", amended["outputs"])
        self.assertEqual(amended["next_roles"][0], "cinematographer")
        self.assertGreaterEqual(len(self.production.history(self.tenant, self.run_id)["outputs"]), 7)

    def test_failed_generation_remains_blocked_without_retry(self):
        self.production.start(self.tenant, self.actor, self.run_id)
        claimed = self.production.claim(self.tenant, self.actor, self.run_id, 0)
        state = self.production.finish(self.tenant, self.actor, self.run_id,
                                       claimed["revision"], "screenwriter", error="provider_timeout")
        self.assertEqual(state["phase"], "blocked_failure")
        with self.assertRaises(RunConflict):
            self.production.claim(self.tenant, self.actor, self.run_id, state["revision"])
        self.assertEqual(self.production.history(self.tenant, self.run_id)["outputs"][0]["error_code"],
                         "provider_timeout")


if __name__ == "__main__":
    unittest.main()
