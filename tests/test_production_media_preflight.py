"""MEDIA-005 pre-flight guards: missing Piper/FFmpeg prerequisites fail closed.

Covers the independent part of the B0 decision: without a Piper binary, a
local Piper model or an FFmpeg converter, voice and video production must
answer an explicit stable error before any reservation is taken.
"""
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from apps.api.dependencies import ProductionMediaConfig
from editorial.media.contracts import Identity
from production.media_pipeline import (
    GenerateVoice, GenerateVideo, ProductionMediaCapacity, ProductionMediaError,
)


def _fake_executable(directory, name):
    """Real executable file, so shutil.which() succeeds whatever the host PATH holds."""
    path = Path(directory) / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class _StubRepository:
    def __init__(self):
        self.reserved = []

    def plan(self, identity, run_id):
        return {"approved": True, "duration_seconds": 75,
                "scenes": [{"duration_seconds": 75, "narration": "Bonjour."}],
                "scenario_id": str(uuid4()), "ready_for_video": True}

    def inputs(self, identity, run_id, kind):
        return {}

    def reserve(self, identity, run_id, kind, scenario_id):
        self.reserved.append((kind, scenario_id))
        return {"asset_id": "asset", "subtitles_id": "subtitles", "attempt": 1}

    def complete(self, identity, run_id, kind, **kwargs):
        return {"kind": kind}

    def fail(self, identity, run_id, kind, scenario_id=None, error_code=None):
        pass


class ProductionMediaPreflightTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.identity = Identity(uuid4(), uuid4())
        self.run_id = uuid4()
        self.model = Path(self.temp.name) / "fr_FR-siwis-medium.onnx"
        self.model.write_bytes(b"onnx-bytes")
        self.piper = _fake_executable(self.temp.name, "piper")
        self.ffmpeg = _fake_executable(self.temp.name, "ffmpeg")
        self.missing = str(Path(self.temp.name) / "absent")

    def config(self, **overrides):
        values = {"piper_bin": self.piper, "piper_model": str(self.model),
                  "ffmpeg_bin": self.ffmpeg, "media_directory": self.temp.name}
        values.update(overrides)
        return ProductionMediaConfig(**values)

    async def assertVoiceRefused(self, config):
        repository = _StubRepository()
        service = GenerateVoice(repository, None, lambda *a, **k: None,
                                ProductionMediaCapacity(), config)
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "voice_provider_unconfigured")
        self.assertEqual(repository.reserved, [])

    async def test_voice_is_accepted_when_every_prerequisite_is_present(self):
        self.assertTrue(self.config().voice_configured())

    async def test_voice_unconfigured_when_piper_binary_is_missing(self):
        await self.assertVoiceRefused(self.config(piper_bin=self.missing))

    async def test_voice_unconfigured_when_model_is_missing(self):
        await self.assertVoiceRefused(
            self.config(piper_model=str(Path(self.temp.name) / "absent.onnx")))

    async def test_voice_unconfigured_when_model_is_empty(self):
        self.model.write_bytes(b"")
        await self.assertVoiceRefused(self.config())

    async def test_voice_unconfigured_when_ffmpeg_converter_is_missing(self):
        await self.assertVoiceRefused(self.config(ffmpeg_bin=self.missing))

    async def assertVideoRefused(self, missing_tool):
        repository = _StubRepository()
        service = GenerateVideo(repository, None, lambda *a, **k: None,
                                ProductionMediaCapacity(), self.config())
        found = lambda name: None if name == missing_tool else "/usr/bin/" + name
        with patch("apps.api.dependencies.shutil.which", side_effect=found):
            with self.assertRaises(ProductionMediaError) as caught:
                await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "video_provider_unconfigured")
        self.assertEqual(repository.reserved, [])

    async def test_video_unconfigured_when_ffmpeg_is_missing(self):
        await self.assertVideoRefused("ffmpeg")

    async def test_video_unconfigured_when_ffprobe_is_missing(self):
        await self.assertVideoRefused("ffprobe")


if __name__ == "__main__":
    unittest.main()
