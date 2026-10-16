import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

spec = importlib.util.spec_from_file_location("render_episode", Path(__file__).resolve().parents[1] / "scripts/render_episode.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EpisodeExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "production.json"
        self.data = {"schema_version": 1, "approved": True, "scenes": [
            {"image": "scene.png", "duration_seconds": 1, "narration": "Première scène."},
            {"image": "scene.png", "duration_seconds": 1, "narration": "Deuxième scène."}]}

    def save(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")

    def test_rejects_unapproved_without_creating_destination(self):
        self.data["approved"] = False
        self.save()
        with self.assertRaisesRegex(ValueError, "approved_manifest_required"):
            module.render(self.manifest, self.root / "export")
        self.assertFalse((self.root / "export").exists())

    def test_rejects_path_escape_and_preserves_existing_export(self):
        self.data["scenes"][0]["image"] = "../outside.png"
        self.save()
        with self.assertRaisesRegex(ValueError, "asset_path_invalid"):
            module.render(self.manifest, self.root / "export")
        (self.root / "export").mkdir()
        (self.root / "export/keep").write_text("original")
        with self.assertRaisesRegex(ValueError, "destination_exists"):
            module.render(self.manifest, self.root / "export")
        self.assertEqual((self.root / "export/keep").read_text(), "original")

    def test_failed_render_cleans_only_new_destination(self):
        (self.root / "scene.png").write_bytes(b"invalid PNG")
        self.save()
        with patch.object(module.shutil, "which", return_value="ffmpeg"), patch.object(module, "run", side_effect=ValueError("media_command_failed")):
            with self.assertRaisesRegex(ValueError, "media_command_failed"):
                module.render(self.manifest, self.root / "export")
        self.assertFalse((self.root / "export").exists())
        self.assertEqual((self.root / "scene.png").read_bytes(), b"invalid PNG")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg export prerequisite absent")
    def test_real_mp4_audio_subtitles_and_reproducible_folder(self):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", "-threads", "1", str(self.root / "scene.png")], check=True)
        with wave.open(str(self.root / "voice.wav"), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 32000)
        self.data["voice"] = "voice.wav"
        self.save()
        receipt = module.render(self.manifest, self.root / "export")
        self.assertTrue(receipt["audio"])
        self.assertEqual(receipt["duration_seconds"], 2)
        probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(self.root / "export/episode.mp4")]))
        self.assertEqual({stream["codec_type"] for stream in probe["streams"]}, {"video", "audio"})
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (720, 1280))
        self.assertIn("00:00:01,000 --> 00:00:02,000", (self.root / "export/narration.srt").read_text())
        replay = module.render(self.root / "export/production.json", self.root / "replay")
        self.assertEqual(replay["scenes"], receipt["scenes"])
        self.assertEqual(replay["voice_sha256"], receipt["voice_sha256"])
