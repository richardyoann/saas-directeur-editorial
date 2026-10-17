"""Offline pipeline contracts and real FFmpeg integration, synthetic inputs only."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4, uuid5
import wave

from production.crew import MAX_SCORES, SPECIALISTS, source_snapshot
from production.episode_pipeline import fingerprint, prepare_manifest, render_production


def fixture():
    run_id = uuid4()
    scene = {"title": "Le phare", "duration_seconds": 15,
             "narration": "Une gardienne observe la mer.", "visual_description": "Un phare dans la brume",
             "characters": ["Gardienne"], "landscape": "Côte bretonne", "colors": ["gris"],
             "shot": "Plan large", "emotion": "Mystère", "sound": "Vagues", "image_prompt": "Phare fictif"}
    run = {"id": str(run_id), "type": "editorial_run", "status": "approved",
           "review_revision": 2, "storyboard_stale": False,
           "brief": {"topic": "Le phare fictif", "scene_count": 5, "duration_seconds": 75, "genre": "fiction"},
           "storyboard": {"title": "Le phare", "synopsis": "Un récit fictif breton.",
                          "scenes": [dict(scene) for _ in range(5)]}}
    source = source_snapshot(run)
    critic = {**MAX_SCORES, "observations": ["Préproduction cohérente à relire."],
              "blocking_issues": [], "target_roles": []}
    specialist = {"summary": "Un plan de production fictif pour le test.",
                  "directions": ["Conserver le scénario approuvé."],
                  "constraints_checked": ["Durée totale de 75 secondes."],
                  "handoff": "Passer au spécialiste suivant."}
    session = {"type": "production_crew_session", "id": str(uuid5(run_id, "production-crew-v1:2")),
               "run_id": str(run_id), "source_revision": 2, "source": source,
               "source_hash": fingerprint(source), "phase": "ready_for_human_review", "stale": False,
               "current_role": None, "next_roles": [], "critique": critic,
               "outputs": {**{role: copy.deepcopy(specialist) for role in SPECIALISTS}, "critic": critic}}
    return {"schema_version": 1, "run": run, "production": session,
            "media": {"images": [{"scene_index": index, "image": "scene.png"} for index in range(1, 6)],
                      "voice": "voice.wav"}}


class PlanTests(unittest.TestCase):
    def test_manifest_uses_only_locked_storyboard_and_keeps_inputs(self):
        bundle = fixture()
        before = copy.deepcopy(bundle)
        result = prepare_manifest(bundle, human_review_confirmed=True)
        self.assertEqual(sum(scene["duration_seconds"] for scene in result["scenes"]), 75)
        self.assertEqual(result["scenes"][0]["narration"], bundle["run"]["storyboard"]["scenes"][0]["narration"])
        self.assertEqual(result["preproduction"]["approval_scope"], "offline_operator_declaration")
        self.assertEqual(bundle, before)

    def test_explicit_human_review_is_required(self):
        for value in (False, None, 1, "true"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "human_review_confirmation_required"):
                prepare_manifest(fixture(), human_review_confirmed=value)

    def test_unapproved_or_modified_storyboard_is_rejected(self):
        for key, value in (("status", "waiting_validation"), ("storyboard_stale", True), ("review_revision", 3)):
            bundle = fixture()
            bundle["run"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare_manifest(bundle, human_review_confirmed=True)
        bundle = fixture()
        bundle["run"]["storyboard"]["scenes"][0]["narration"] = "Un texte modifié après la préproduction."
        with self.assertRaisesRegex(ValueError, "production_source_mismatch"):
            prepare_manifest(bundle, human_review_confirmed=True)

    def test_incomplete_running_stale_or_mixed_session_is_rejected(self):
        for key, value in (("phase", "blocked_quality"), ("stale", True), ("stale", None),
                           ("current_role", "critic"), ("next_roles", ["critic"]),
                           ("run_id", str(uuid4())), ("id", str(uuid4())),
                           ("source_hash", "0" * 64), ("source_revision", True)):
            bundle = fixture()
            bundle["production"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare_manifest(bundle, human_review_confirmed=True)

    def test_quality_is_recomputed_instead_of_trusting_a_passed_flag(self):
        bundle = fixture()
        bundle["production"]["quality"] = {"passed": True, "score": 100}
        bundle["production"]["critique"]["narrative"] = 0
        with self.assertRaisesRegex(ValueError, "production_quality_rejected"):
            prepare_manifest(bundle, human_review_confirmed=True)

    def test_missing_output_and_conflicting_critique_are_rejected(self):
        bundle = fixture()
        bundle["production"]["outputs"].pop("editor")
        with self.assertRaisesRegex(ValueError, "production_outputs_incomplete"):
            prepare_manifest(bundle, human_review_confirmed=True)
        bundle = fixture()
        bundle["production"]["critique"] = dict(bundle["production"]["critique"], narrative=19)
        with self.assertRaisesRegex(ValueError, "production_quality_rejected"):
            prepare_manifest(bundle, human_review_confirmed=True)

    def test_media_bindings_are_complete_and_ordered_and_voice_required(self):
        for change in ("missing_image", "reordered", "no_voice", "boolean_index"):
            bundle = fixture()
            media = bundle["media"]
            if change == "missing_image":
                media["images"].pop()
            elif change == "reordered":
                media["images"][0]["scene_index"] = 2
            elif change == "boolean_index":
                media["images"][0]["scene_index"] = True
            else:
                media.pop("voice")
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_manifest(bundle, human_review_confirmed=True)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.media = self.root / "media"
        self.media.mkdir()
        (self.media / "scene.png").write_bytes(b"placeholder PNG")
        (self.media / "voice.wav").write_bytes(b"placeholder WAV")
        self.bundle = fixture()
        self.path = self.root / "bundle.json"
        self.destination = self.root / "output"
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.bundle), encoding="utf-8")

    def invoke(self):
        return render_production(self.path, self.media, self.destination, human_review_confirmed=True)

    def test_rejected_plan_does_not_create_output_or_invoke_renderer(self):
        self.bundle["production"]["phase"] = "running"
        self.save()
        with patch("production.episode_pipeline.render") as called:
            with self.assertRaises(ValueError):
                self.invoke()
            called.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_path_escape_and_symlinks_are_rejected(self):
        self.bundle["media"]["images"][0]["image"] = "../outside.png"
        (self.root / "outside.png").write_bytes(b"outside")
        self.save()
        with self.assertRaisesRegex(ValueError, "asset_path_invalid"):
            self.invoke()
        self.bundle = fixture()
        (self.media / "scene.png").unlink()
        (self.media / "scene.png").symlink_to(self.root / "outside.png")
        self.save()
        with self.assertRaisesRegex(ValueError, "asset_symlink_forbidden"):
            self.invoke()
        self.assertFalse(self.destination.exists())

    def test_existing_destination_is_preserved(self):
        self.destination.mkdir()
        (self.destination / "keep").write_text("original")
        with self.assertRaisesRegex(ValueError, "destination_exists"):
            self.invoke()
        self.assertEqual((self.destination / "keep").read_text(), "original")

    def test_command_failure_is_not_retried_and_has_only_fixed_receipt(self):
        with patch("production.episode_pipeline.render", side_effect=ValueError("private diagnostic")) as called:
            with self.assertRaises(ValueError):
                self.invoke()
            called.assert_called_once()
        receipt = (self.destination / "pipeline_receipt.json").read_text()
        self.assertNotIn("private diagnostic", receipt)
        self.assertEqual(json.loads(receipt)["status"], "failed_or_interrupted")
        self.assertEqual((self.media / "scene.png").read_bytes(), b"placeholder PNG")
        self.assertFalse(any(self.destination.glob(".inputs-*")))

    def test_duplicate_json_keys_are_rejected_before_render(self):
        self.path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            self.invoke()
        self.assertFalse(self.destination.exists())

    def test_technical_rejection_retains_export_and_never_claims_success(self):
        def fake_render(manifest, destination):
            destination.mkdir()
            (destination / "receipt.json").write_text('{}')
            (destination / "episode.mp4").write_bytes(b"synthetic")
            return {"video_sha256": "0" * 64, "duration_seconds": 75}
        rejected = {"technical_passed": False, "findings": ["subtitles_overlap"],
                    "visual_review_required": True, "human_release_required": True}
        with patch("production.episode_pipeline.render", side_effect=fake_render) as called, \
             patch("production.episode_pipeline.inspect_export", return_value=rejected):
            result = self.invoke()
            called.assert_called_once()
        self.assertFalse(result["technical_passed"])
        self.assertTrue((self.destination / "export" / "episode.mp4").is_file())
        receipt = json.loads((self.destination / "pipeline_receipt.json").read_text())
        self.assertEqual(receipt["status"], "technical_rejected")
        self.assertFalse(receipt["automatic_retry_allowed"])

    def test_cli_errors_do_not_print_private_inputs(self):
        self.path.write_text("private input that is not JSON")
        reply = subprocess.run([sys.executable, "scripts/render_production.py", str(self.path),
                                str(self.media), str(self.destination)], capture_output=True, text=True)
        self.assertEqual(reply.returncode, 2)
        self.assertNotIn(str(self.root), reply.stderr)
        self.assertNotIn("private input", reply.stderr)
        self.assertNotIn("Traceback", reply.stderr)

    def test_real_pipeline_keeps_sources_and_produces_qualified_75s_export(self):
        self.assertIsNotNone(shutil.which("ffmpeg"), "FFmpeg required; no skipped validation")
        self.assertIsNotNone(shutil.which("ffprobe"))
        (self.media / "scene.png").unlink()
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=blue:s=64x64", "-frames:v", "1", "-threads", "1",
                        str(self.media / "scene.png")], check=True, capture_output=True, timeout=20)
        with wave.open(str(self.media / "voice.wav"), "wb") as voice:
            voice.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            voice.writeframes(b"\x00\x00" * 16000 * 75)
        before = {path.name: path.read_bytes() for path in self.media.iterdir()}
        reply = self.invoke()
        self.assertTrue(reply["technical_passed"])
        self.assertTrue(reply["human_release_required"])
        self.assertEqual(reply["duration_seconds"], 75)
        self.assertNotIn(str(self.root), json.dumps(reply))
        receipt = json.loads((self.destination / "pipeline_receipt.json").read_text())
        self.assertEqual(receipt["status"], "technical_passed")
        self.assertEqual(receipt["preproduction"]["source_revision"], 2)
        self.assertEqual(len(receipt["video_sha256"]), 64)
        manifest = json.loads((self.destination / "export" / "production.json").read_text())
        self.assertEqual(manifest["preproduction"]["source_sha256"], self.bundle["production"]["source_hash"])
        self.assertEqual([scene["image"] for scene in manifest["scenes"]],
                         [f"scene-{i}.png" for i in range(1, 6)])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.media.iterdir()})
        self.assertFalse(any(self.destination.glob(".inputs-*")))
