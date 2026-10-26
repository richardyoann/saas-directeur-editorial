"""SRT quality gate tests; synthetic text and a real FFmpeg export."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from production.media_qc import inspect_export, validate_subtitles
import test_render_critic


class SubtitleTests(unittest.TestCase):
    def test_valid_multiline_crlf_and_bom(self):
        self.assertIsNone(validate_subtitles("\ufeff1\r\n00:00:00,000 --> 00:00:15,000\r\nLe phare\r\nse réveille.\r\n\r\n2\r\n00:00:15,000 --> 00:01:15,000\r\nLa mer.\r\n"))

    def test_empty(self):
        for text in ("", "  \n"):
            self.assertEqual(validate_subtitles(text), "subtitles_empty")

    def test_structure(self):
        for text in ("garbage", "2\n00:00:00,000 --> 00:00:01,000\nTexte",
                     "1\n00:00:00,000 --> 00:00:01,000"):
            self.assertEqual(validate_subtitles(text), "subtitles_structure_invalid")

    def test_timestamp(self):
        for value in ("00:60:00,000", "00:00:00.000", "-1:00:00,000"):
            self.assertEqual(validate_subtitles(f"1\n{value} --> 00:01:15,000\nTexte"), "subtitles_timestamp_invalid")

    def test_invalid_interval(self):
        for start, end in (("00:00:01,000", "00:00:01,000"),
                           ("00:00:02,000", "00:00:01,000"),
                           ("00:00:00,000", "00:01:15,001")):
            self.assertEqual(validate_subtitles(f"1\n{start} --> {end}\nTexte"), "subtitles_timing_invalid")

    def test_overlap(self):
        self.assertEqual(validate_subtitles("1\n00:00:00,000 --> 00:00:05,000\nTexte\n\n2\n00:00:04,999 --> 00:00:10,000\nSuite"), "subtitles_overlap")

    def test_whitespace_caption(self):
        self.assertEqual(validate_subtitles("1\n00:00:00,000 --> 00:00:01,000\n \n\n2\n00:00:01,000 --> 00:00:02,000\nSuite"), "subtitles_structure_invalid")


class SubtitleGateTests(unittest.TestCase):
    setUp = test_render_critic.RenderCriticTests.setUp
    write_receipt = test_render_critic.RenderCriticTests.write_receipt
    inspect = test_render_critic.RenderCriticTests.inspect
    def test_invalid_srt_blocks_otherwise_valid_export(self):
        (self.root / "narration.srt").write_text("not an SRT", encoding="utf-8")
        report = self.inspect()
        self.assertFalse(report["technical_passed"])
        self.assertIn("subtitles_structure_invalid", report["findings"])
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_invalid_utf8_is_rejected(self):
        (self.root / "narration.srt").write_bytes(b"\xff")
        self.assertFalse(self.inspect()["technical_passed"])


class RealExportTests(unittest.TestCase):
    def test_real_mp4_and_subtitle_rejection(self):
        ffmpeg = shutil.which("ffmpeg")
        self.assertIsNotNone(ffmpeg, "FFmpeg required; no skip counts as validation")
        self.assertIsNotNone(shutil.which("ffprobe"))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            video = folder / "episode.mp4"
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi",
                            "-i", "color=c=black:s=720x1280:r=24",
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                            "-t", "75", "-c:v", "libx264", "-threads", "1",
                            "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", str(video)],
                           check=True, capture_output=True, timeout=120)
            (folder / "receipt.json").write_text(json.dumps({
                "schema_version": 1, "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "duration_seconds": 75, "width": 720, "height": 1280, "audio": True}))
            srt = folder / "narration.srt"
            srt.write_text("1\n00:00:00,000 --> 00:01:15,000\nTexte synthétique.\n", encoding="utf-8")
            self.assertTrue(inspect_export(folder)["technical_passed"])
            srt.write_text("1\n00:00:00,000 --> 00:01:16,000\nTexte synthétique.\n", encoding="utf-8")
            result = inspect_export(folder)
            self.assertFalse(result["technical_passed"])
            self.assertIn("subtitles_timing_invalid", result["findings"])

