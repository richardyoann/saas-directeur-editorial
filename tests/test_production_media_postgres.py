"""Real PostgreSQL integration cases; ONLY the dedicated disposable test database."""
import copy
import json
import os
import unittest
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from editorial.models import Brief
from editorial.store import PostgresStore, RunConflict, RunMissing
from infrastructure.persistence.production_media_repository import (
    PostgresProductionMediaRepository, ProductionMediaAdapter,
)


def storyboard():
    scene = {"title": "Le rivage", "duration_seconds": 25,
             "narration": "Une légende raconte la mer.", "visual_description": "Un rivage",
             "characters": ["Un marin"], "landscape": "Côte bretonne",
             "colors": ["bleu"], "shot": "Plan large", "emotion": "Mystère",
             "sound": "Vagues", "image_prompt": "Un rivage sous la brume"}
    return {"title": "La mer", "synopsis": "Récit légendaire",
            "scenes": [copy.deepcopy(scene) for _ in range(3)]}


def analysis():
    return {"angle": "Une légende maritime", "message": "Le rapport à la mer",
            "historical_checks": ["Vérifier les variantes de la légende"]}


@unittest.skipUnless(os.getenv("PO_TEST_DATABASE_URL"), "dedicated PostgreSQL test target not configured")
class ProductionMediaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes":
            raise RuntimeError("test migration not authorized")
        cls.store = PostgresStore(os.environ["PO_TEST_DATABASE_URL"])
        with cls.store.connect() as conn:
            conn.execute(Path("pilotage/migration.sql").read_text())

    def setUp(self):
        self.tenant, self.actor = uuid4(), uuid4()
        self.repository = PostgresProductionMediaRepository(
            self.store.connect, self.store._write, self.store.get,
            lambda: "2026-10-28T00:00:00Z", lambda: "test-sha")

    def approved_run(self, *, images=True):
        run, _ = self.store.start(self.tenant, self.actor, uuid4(),
                                  Brief(topic="Le phare fictif", duration_seconds=75,
                                        scene_count=3, genre="fiction").model_dump())
        run_id = UUID(run["id"])
        for step, parsed in (("analysis", analysis()), ("storyboard", storyboard())):
            self.store.begin_step(self.tenant, self.actor, run_id, step, "prompt")
            self.store.save_step(self.tenant, self.actor, run_id, step, "prompt",
                                 {"response": json.dumps(parsed), "finish_reason": "stop"},
                                 parsed)
        self.store.review(self.tenant, self.actor, run_id, "analysis",
                          {"action": "accept", "expected_revision": 0})
        state = self.store.review(self.tenant, self.actor, run_id, "storyboard",
                                  {"action": "accept", "expected_revision": 1})
        self.assertEqual(state["status"], "approved")
        content = self.store.get(self.tenant, run_id)
        if images:
            with self.store.connect() as conn:
                for scene_id in content["scene_ids"]:
                    asset_id = uuid5(UUID(scene_id), "private-image-v1")
                    self.store._write(
                        conn, self.tenant, self.actor, run_id, "result", asset_id,
                        {"type": "scene_image_asset", "run_id": str(run_id),
                         "scenario_id": content["scenario_id"], "scene_id": str(scene_id),
                         "scene_number": 1, "status": "ready",
                         "storage": f"private/{scene_id}.png", "sha256": "a" * 64,
                         "byte_count": 42, "mime_type": "image/png"})
        return run_id, content["scenario_id"], content["scene_ids"]

    def ready_voice(self, run_id, scenario_id):
        reservation = self.repository.reserve(self.tenant, self.actor, run_id, "voice",
                                              scenario_id=scenario_id)
        return self.repository.complete(
            self.tenant, self.actor, run_id, "voice", scenario_id=scenario_id,
            storage={"kind": "voice", "backend": "file", "path": "/private/voice.wav"},
            sha256="b" * 64, byte_count=1200, duration_seconds=75)

    def test_plan_reports_prerequisites_media_and_tenant_isolation(self):
        run_id, scenario_id, scene_ids = self.approved_run()
        plan = self.repository.plan(self.tenant, run_id)
        self.assertTrue(plan["approved"])
        self.assertTrue(plan["ready_for_voice"])
        self.assertFalse(plan["ready_for_video"])
        self.assertEqual(plan["missing_images"], [])
        self.assertEqual(plan["duration_seconds"], 75)
        self.assertEqual(plan["media"], {})
        self.assertEqual([scene["image_status"] for scene in plan["scenes"]],
                         ["ready", "ready", "ready"])

        self.ready_voice(run_id, scenario_id)
        plan = self.repository.plan(self.tenant, run_id)
        self.assertTrue(plan["ready_for_video"])
        self.assertEqual(plan["media"]["voice"]["status"], "ready")
        self.assertEqual(plan["media"]["voice"]["duration_seconds"], 75)

        with self.assertRaises(RunMissing):
            self.repository.plan(uuid4(), run_id)

    def test_plan_without_images_is_not_ready_for_video(self):
        run_id, scenario_id, _ = self.approved_run(images=False)
        plan = self.repository.plan(self.tenant, run_id)
        self.assertTrue(plan["ready_for_voice"])
        self.assertFalse(plan["ready_for_video"])
        self.assertEqual(plan["missing_images"], [1, 2, 3])
        self.ready_voice(run_id, scenario_id)
        self.assertFalse(self.repository.plan(self.tenant, run_id)["ready_for_video"])

    def test_reservation_conflicts_and_tenant_isolation(self):
        run_id, scenario_id, _ = self.approved_run()
        reservation = self.repository.reserve(self.tenant, self.actor, run_id, "voice",
                                              scenario_id=scenario_id)
        self.assertEqual(reservation["attempt"], 1)
        self.assertEqual(reservation["asset_id"],
                         self.repository.asset_id(scenario_id, "voice"))
        with self.assertRaises(RunConflict):
            self.repository.reserve(self.tenant, self.actor, run_id, "voice",
                                    scenario_id=scenario_id)
        with self.assertRaises(RunMissing):
            self.repository.reserve(uuid4(), self.actor, run_id, "voice",
                                    scenario_id=scenario_id)
        with self.assertRaises(RunConflict):
            self.repository.reserve(self.tenant, self.actor, run_id, "voice",
                                    scenario_id=str(uuid4()))

    def test_failed_voice_can_be_retried_with_an_incremented_attempt(self):
        run_id, scenario_id, _ = self.approved_run()
        self.repository.reserve(self.tenant, self.actor, run_id, "voice",
                                scenario_id=scenario_id)
        self.repository.fail(self.tenant, self.actor, run_id, "voice",
                             scenario_id=scenario_id, error_code="tts_engine_failed")
        plan = self.repository.plan(self.tenant, run_id)
        self.assertEqual(plan["media"]["voice"]["status"], "failed")
        self.assertEqual(plan["media"]["voice"]["error_code"], "tts_engine_failed")
        retried = self.repository.reserve(self.tenant, self.actor, run_id, "voice",
                                          scenario_id=scenario_id)
        self.assertEqual(retried["attempt"], 2)
        self.repository.fail(self.tenant, self.actor, run_id, "voice",
                             scenario_id=scenario_id, error_code="voice_provider_timeout")
        plan = self.repository.plan(self.tenant, run_id)
        self.assertEqual(plan["media"]["voice"]["status"], "failed")

    def test_complete_requires_a_reservation_and_exposes_a_scoped_reference(self):
        run_id, scenario_id, _ = self.approved_run()
        with self.assertRaises(RunConflict):
            self.repository.complete(
                self.tenant, self.actor, run_id, "voice", scenario_id=scenario_id,
                storage={"kind": "voice"}, sha256="b" * 64, byte_count=10)
        result = self.ready_voice(run_id, scenario_id)
        reference = self.repository.reference(self.tenant, run_id,
                                              UUID(result["media_id"]))
        self.assertEqual(reference["kind"], "voice")
        self.assertEqual(reference["sha256"], "b" * 64)
        self.assertEqual(reference["size"], 1200)
        with self.assertRaises(RunMissing):
            self.repository.reference(uuid4(), run_id, UUID(result["media_id"]))
        with self.assertRaises(RunMissing):
            self.repository.reference(self.tenant, uuid4(), UUID(result["media_id"]))

    def test_video_completion_publishes_subtitles_atomically(self):
        run_id, scenario_id, scene_ids = self.approved_run()
        self.ready_voice(run_id, scenario_id)
        inputs = self.repository.inputs(self.tenant, run_id, "video")
        self.assertEqual(inputs["total_seconds"], 75)
        self.assertEqual(len(inputs["images"]), 3)
        self.assertTrue(all(image["asset_id"] for image in inputs["images"]))
        self.assertEqual([image["scene_id"] for image in inputs["images"]],
                         [str(scene_id) for scene_id in scene_ids])
        self.assertEqual(inputs["voice"]["asset_id"],
                         str(self.repository.asset_id(scenario_id, "voice")))
        reservation = self.repository.reserve(self.tenant, self.actor, run_id, "video",
                                              scenario_id=scenario_id)
        result = self.repository.complete(
            self.tenant, self.actor, run_id, "video", scenario_id=scenario_id,
            storage={"kind": "video", "backend": "file", "path": "/private/video.mp4"},
            sha256="c" * 64, byte_count=9000, duration_seconds=75,
            extra_storage={"subtitles": {"reference": {"kind": "subtitles",
                                                       "backend": "file",
                                                       "path": "/private/subtitles.srt"},
                                         "sha256": "d" * 64, "size": 120}})
        self.assertEqual(result["media_id"], str(reservation["asset_id"]))
        plan = self.repository.plan(self.tenant, run_id)
        self.assertEqual(plan["media"]["video"]["status"], "ready")
        self.assertEqual(plan["media"]["subtitles"]["status"], "ready")
        subtitles = self.repository.reference(self.tenant, run_id,
                                              reservation["subtitles_id"])
        self.assertEqual(subtitles["kind"], "subtitles")
        self.assertEqual(subtitles["sha256"], "d" * 64)
        with self.assertRaises(RunConflict):
            self.repository.reserve(self.tenant, self.actor, run_id, "video",
                                    scenario_id=scenario_id)

    def test_audit_and_outbox_stay_atomic_for_each_media_write(self):
        run_id, scenario_id, _ = self.approved_run()
        self.ready_voice(run_id, scenario_id)
        asset_id = self.repository.asset_id(scenario_id, "voice")
        with self.store.connect() as conn:
            counts = conn.execute(
                "SELECT (SELECT count(*) FROM po_audit WHERE correlation_id=%s AND entity_id=%s),"
                " (SELECT count(*) FROM po_outbox o JOIN po_audit a USING(event_id)"
                "  WHERE a.correlation_id=%s AND a.entity_id=%s)",
                (run_id, asset_id, run_id, asset_id)).fetchone()
        self.assertEqual(counts[0], 2)
        self.assertEqual(counts[0], counts[1])

    def test_unapproved_or_stale_scenario_is_rejected(self):
        run_id, scenario_id, _ = self.approved_run()
        with self.store.connect() as conn:
            version, content = conn.execute(
                "SELECT version, content FROM po_entity WHERE tenant_id=%s "
                "AND kind='treatment' AND entity_id=%s AND NOT deleted",
                (self.tenant, run_id)).fetchone()
            self.store._write(
                conn, self.tenant, self.actor, run_id, "treatment", run_id,
                {**content, "storyboard_stale": True}, version=version)
        plan = self.repository.plan(self.tenant, run_id)
        self.assertFalse(plan["approved"])
        with self.assertRaises(RunConflict):
            self.repository.reserve(self.tenant, self.actor, run_id, "voice",
                                    scenario_id=scenario_id)

    def test_adapter_translates_database_failures_only(self):
        class Broken:
            def plan(self, *args, **kwargs):
                import psycopg
                raise psycopg.OperationalError("down")

            def inputs(self, *args, **kwargs):
                return {"scenario_id": "x"}

        from editorial.media.contracts import Identity, PersistenceUnavailable
        adapter = ProductionMediaAdapter(Broken())
        identity = Identity(self.tenant, self.actor)
        with self.assertRaises(PersistenceUnavailable):
            adapter.plan(identity, uuid4())
        self.assertEqual(adapter.inputs(identity, uuid4(), "voice"), {"scenario_id": "x"})


if __name__ == "__main__":
    unittest.main()
