"""Tests for deterministic voice timeline and guarded local Piper use."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from production.voice_timeline import synthesize_voice


class VoiceTimelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.model = self.root / "fr.onnx"
        self.model.write_bytes(b"test-model-file")
        self.output = self.root / "voice.wav"
        self.scenes = [{"duration_seconds": 25, "narration": f"Histoire scène {i}."}
                       for i in range(3)]
        self.stub = self.root / "piper-test"
        self.stub.write_text("""#!/usr/bin/env python3
import sys, wave
from pathlib import Path
file = Path(sys.argv[sys.argv.index('--output_file') + 1])
text = sys.stdin.read()
frames = 16000 * (30 if 'trop-longue' in text else 1)
with wave.open(str(file), 'wb') as w:
    w.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
    w.writeframes(b'\\x12\\x34' * frames)
""")
        self.stub.chmod(0o700)

    def call(self):
        return synthesize_voice(self.scenes, self.model, self.output,
                                piper=str(self.stub))

    def test_real_ffmpeg_and_stub_tts_create_exact_75s_wav(self):
        self.assertIsNotNone(shutil.which("ffmpeg"), "ffmpeg required, no skips")
        result = self.call()
        self.assertTrue(result["voice_created"])
        self.assertEqual(result["duration_seconds"], 75)
        self.assertEqual(result["scene_count"], 3)
        with wave.open(str(self.output), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.getnframes(), 75 * 24000)
            first_scene = wav.readframes(25 * 24000)
            self.assertTrue(any(first_scene[:1000]))
            self.assertEqual(first_scene[-1000:], bytes(1000))
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)
        self.assertFalse(any(self.root.glob('.tts-*')))

    def test_speech_longer_than_scene_refused_without_overwrite(self):
        self.scenes[0]["narration"] = "trop-longue"
        with self.assertRaisesRegex(ValueError, "tts_scene_too_long"):
            self.call()
        self.assertFalse(self.output.exists())

    def test_existing_voice_is_not_replaced(self):
        self.output.write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError, "voice_destination_invalid"):
            self.call()
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_invalid_total_or_missing_model_fails_before_output(self):
        self.scenes[0]["duration_seconds"] = 24
        with self.assertRaisesRegex(ValueError, "voice_duration_not_75"):
            self.call()
        self.scenes[0]["duration_seconds"] = 25
        self.model.unlink()
        with self.assertRaisesRegex(ValueError, "piper_model_unavailable"):
            self.call()
        self.assertFalse(self.output.exists())

    def test_symlink_destination_refused(self):
        outside = self.root / "outside.wav"
        outside.write_bytes(b"protected")
        self.output.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "voice_destination_invalid"):
            self.call()
        self.assertEqual(outside.read_bytes(), b"protected")
