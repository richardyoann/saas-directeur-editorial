"""MEDIA-005 pre-flight guards: missing Piper/FFmpeg prerequisites fail closed.

Covers the independent part of the B0 decision: without a Piper binary, a
local Piper model or an FFmpeg converter, voice and video production must
answer an explicit stable error before any reservation is taken.
"""
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

    def config(self, *, piper_bin="piper", piper_model=None, ffmpeg_bin="ffmpeg"):
        return ProductionMediaConfig(
            piper_bin=piper_bin,
            piper_model=str(piper_model if piper_model is not None else self.model),
            ffmpeg_bin=ffmpeg_bin,
            media_directory=self.temp.name)

    async def test_voice_unconfigured_when_piper_binary_is_missing(self):
        repository = _StubRepository()
        service = GenerateVoice(repository, None, lambda *a, **k: None,
                                ProductionMediaCapacity(),
                                self.config(piper_bin=str(Path(self.temp.name) / "missing-piper")))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "voice_provider_unconfigured")
        self.assertEqual(repository.reserved, [])

    async def test_voice_unconfigured_when_model_is_missing_or_empty(self):
        self.model.write_bytes(b"")
        for model in (None, self.model):
            with self.subTest(model=model is not None):
                repository = _StubRepository()
                service = GenerateVoice(repository, None, lambda *a, **k: None,
                                       ProductionMediaCapacity(),
                                       self.config(piper_model=model))
                with self.assertRaises(ProductionMediaError) as caught:
                    await service.execute(self.identity, self.run_id)
                self.assertEqual(caught.exception.code, "voice_provider_unconfigured")
                self.assertEqual(repository.reserved, [])

    async def test_voice_unconfigured_when_ffmpeg_converter_is_missing(self):
        repository = _StubRepository()
        service = GenerateVoice(repository, None, lambda *a, **k: None,
                                ProductionMediaCapacity(),
                                self.config(ffmpeg_bin=str(Path(self.temp.name) / "missing-ffmpeg")))
        with self.assertRaises(ProductionMediaError) as caught:
            await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "voice_provider_unconfigured")
        self.assertEqual(repository.reserved, [])

    async def test_video_unconfigured_when_ffmpeg_converter_is_missing(self):
        repository = _StubRepository()
        service = GenerateVideo(repository, None, lambda *a, **k: None,
                                ProductionMediaCapacity(), self.config())
        with patch("apps.api.dependencies.shutil.which", return_value=None):
            with self.assertRaises(ProductionMediaError) as caught:
                await service.execute(self.identity, self.run_id)
        self.assertEqual(caught.exception.code, "video_provider_unconfigured")
        self.assertEqual(repository.reserved, [])


if __name__ == "__main__":
    unittest.main()
