"""Contract checks with fixtures, not proof of a local image model or GPU."""
import copy
import hashlib
import struct
import zlib
import unittest
from unittest.mock import patch

import httpx

from editorial.image_verification import verify_scene, verification_report
from editorial.visuals import ImageUnavailable, image_prompt, image_provenance, render_png
from test_editorial import outputs


def sample_scene():
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 512, 512, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00" * ((512 * 4 + 1) * 512)))
           + chunk(b"IEND", b""))
    scene = {"scene_number": 1, "scene_id": "opaque-scene-id", "image_status": "ready",
             "generation": {"width": 512, "height": 512, "duration_seconds": 1.5,
                            "byte_count": len(png), "png_sha256": hashlib.sha256(png).hexdigest(),
                            "provenance": {"character_reference_sha256": "reference"}}}
    return scene, png


class ImageReceiptContractTests(unittest.IsolatedAsyncioTestCase):
    def test_character_reference_snapshot_is_stable_and_detects_changes(self):
        board = outputs()[1]
        board["cast"] = [{"name": "Un marin", "appearance": "Manteau rouge",
                          "role": "Guide", "personality": "Calme"}]
        run = {"storyboard": board}
        first = image_provenance(run, 1, image_prompt(run, 1))
        second = image_provenance(run, 2, image_prompt(run, 2))
        self.assertEqual(first["character_reference_sha256"], second["character_reference_sha256"])
        self.assertNotEqual(first["prompt_sha256"], second["prompt_sha256"])
        self.assertIsNone(first["model"])
        self.assertIsNone(first["seed"])
        self.assertIsNone(first["vram_peak_bytes"])
        self.assertFalse(first["gpu_verified"])
        board["cast"][0]["appearance"] = "Manteau bleu"
        third = image_provenance(run, 1, image_prompt(run, 1))
        self.assertNotEqual(first["character_reference_sha256"], third["character_reference_sha256"])
        self.assertEqual(first["character_references"][0]["appearance"], "Manteau rouge")

    async def test_timeout_and_http_failure_are_classified_without_retry(self):
        for failure, code in [(httpx.ReadTimeout("private upstream details"), "image_provider_timeout"),
                              (httpx.ConnectError("secret URL"), "image_provider_response_uncertain"),
                              (httpx.Response(503), "image_provider_response_uncertain"),
                              (httpx.Response(422), "image_provider_rejected")]:
            calls = []
            def handler(request):
                calls.append(request)
                if isinstance(failure, Exception):
                    raise failure
                return failure
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ImageUnavailable) as caught:
                    await render_png(client, "http://127.0.0.1:8082", "fixture")
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(len(calls), 1)

    def test_integrity_requires_digest_dimensions_duration_and_audit(self):
        scene, png = sample_scene()
        self.assertTrue(verify_scene(scene, png, 2)["passed"])
        for key, value, reason in [
            ("png_sha256", None, "image_digest_mismatch_or_missing"),
            ("byte_count", 0, "byte_count_mismatch_or_missing"),
            ("duration_seconds", float("nan"), "duration_unavailable"),
            ("duration_seconds", True, "duration_unavailable"),
            ("width", 1, "dimension_metadata_mismatch"),
        ]:
            changed = copy.deepcopy(scene)
            changed["generation"][key] = value
            self.assertIn(reason, verify_scene(changed, png, 2)["reasons"])
        self.assertIn("audit_outbox_incomplete", verify_scene(scene, png, 1)["reasons"])
        self.assertIn("private_file_unavailable", verify_scene(scene, None, 2)["reasons"])
        corrupt = bytearray(png)
        corrupt[45] ^= 1
        self.assertIn("invalid_png", verify_scene(scene, bytes(corrupt), 2)["reasons"])
        self.assertIn("invalid_png", verify_scene(scene, png[:-12], 2)["reasons"])

    def test_technical_report_never_accepts_gpu_or_artistic_quality(self):
        scene, png = sample_scene()
        plan = {"run_id": "run", "approved": True, "scenes": [scene]}
        checks = [verify_scene(scene, png, 2)]
        report = verification_report(plan, checks, 1)
        self.assertTrue(report["technical_passed"])
        self.assertFalse(report["gpu_verified"])
        self.assertIsNone(report["vram_peak_bytes"])
        self.assertTrue(report["human_visual_review_required"])
        self.assertFalse(verification_report(plan, checks, 3)["technical_passed"])
        plan["approved"] = False
        self.assertFalse(verification_report(plan, checks, 1)["technical_passed"])

    def test_distinct_references_block_consistency_and_duplicates_need_review(self):
        scene, png = sample_scene()
        second = copy.deepcopy(scene)
        second["scene_number"] = 2
        second["generation"]["provenance"]["character_reference_sha256"] = "changed"
        plan = {"run_id": "run", "approved": True, "scenes": [scene, second]}
        report = verification_report(plan, [verify_scene(s, png, 2) for s in plan["scenes"]], 2)
        self.assertFalse(report["technical_passed"])
        self.assertTrue(report["duplicate_image_digests"])


if __name__ == "__main__":
    unittest.main()
