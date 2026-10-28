"""Read-only export critic: verified with temporary files and synthetic ffprobe."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from production.media_qc import inspect_export


class RenderCriticTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        (self.root / "episode.mp4").write_bytes(b"synthetic-video-bytes")
        (self.root / "narration.srt").write_text("1\n00:00:00,000 --> 00:00:10,000\nLégende.\n",
                                                  encoding="utf-8")
        self.receipt = {
            "schema_version": 1, "video_sha256": hashlib.sha256(b"synthetic-video-bytes").hexdigest(),
            "duration_seconds": 75, "width": 720, "height": 1280, "audio": True,
        }
        self.write_receipt()

    def write_receipt(self):
        (self.root / "receipt.json").write_text(json.dumps(self.receipt), encoding="utf-8")

    def inspect(self, probe=None):
        data = probe or {
            "format": {"duration": "75.000"},
            "streams": [{"codec_type": "video", "width": 720, "height": 1280,
                         "r_frame_rate": "24/1"},
                        {"codec_type": "audio"}],
        }
        completed = CompletedProcess(args=[], returncode=0, stdout=json.dumps(data).encode())
        with patch("production.media_qc.shutil.which", return_value="/usr/bin/ffprobe"), \
             patch("production.media_qc.subprocess.run", return_value=completed) as called:
            result = inspect_export(self.root)
            if called.called:
                self.assertEqual(called.call_args.kwargs["timeout"], 20)
        return result

    def test_valid_export_still_requires_visual_and_human_review(self):
        report = self.inspect()
        self.assertTrue(report["technical_passed"])
        self.assertTrue(report["visual_review_required"])
        self.assertTrue(report["human_release_required"])
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_cinematic_1080x1920_export_is_accepted(self):
        self.receipt.update({"width": 1080, "height": 1920})
        self.write_receipt()
        report = self.inspect({"format": {"duration": "75.000"},
            "streams": [{"codec_type": "video", "width": 1080, "height": 1920,
                         "r_frame_rate": "24/1"},
                        {"codec_type": "audio"}]})
        self.assertTrue(report["technical_passed"], report["findings"])

    def test_hash_duration_format_audio_and_framerate_are_blocking(self):
        self.receipt["video_sha256"] = "x" * 64
        self.receipt["audio"] = False
        self.write_receipt()
        report = self.inspect({"format": {"duration": "72"},
            "streams": [{"codec_type": "video", "width": 1280, "height": 720,
                         "r_frame_rate": "30/1"}]})
        self.assertFalse(report["technical_passed"])
        for code in ("video_sha256_mismatch", "voice_not_present_in_receipt",
                     "video_duration_not_75", "video_not_9_16",
                     "video_framerate_not_24", "video_audio_streams_invalid"):
            self.assertIn(code, report["findings"])

    def test_missing_or_symlinked_media_is_rejected(self):
        (self.root / "episode.mp4").unlink()
        self.assertFalse(self.inspect()["technical_passed"])
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"x")
        (self.root / "episode.mp4").symlink_to(outside)
        self.assertFalse(self.inspect()["technical_passed"])

    def test_missing_ffprobe_blocks_qualification(self):
        with patch("production.media_qc.shutil.which", return_value=None):
            result = inspect_export(self.root)
        self.assertIn("ffprobe_missing", result["findings"])
        self.assertFalse(result["technical_passed"])


if __name__ == "__main__":
    unittest.main()
