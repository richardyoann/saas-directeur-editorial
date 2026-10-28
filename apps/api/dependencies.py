"""Composition root: concrete media adapters are selected only at the API boundary."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil

from editorial.media.application import GenerateSceneImage, ReadMedia
from infrastructure.images.sdcpp import PrivateImageRenderer
from infrastructure.media import production_media
from infrastructure.media.capacity import image_gate
from infrastructure.media.images import PrivateMediaStorage
from infrastructure.observability import mlflow_tracker
from infrastructure.persistence.media_repository import ImageRepositoryAdapter
from infrastructure.persistence.production_media_repository import ProductionMediaAdapter
from production.media_pipeline import (
    GenerateVideo, GenerateVoice, ProductionMediaCapacity, ReadProductionMedia,
)
from production.voice_timeline import synthesize_voice
from scripts.render_episode import render


def build_image_service(store, client):
    return GenerateSceneImage(ImageRepositoryAdapter(store.media_repository()),
                              PrivateImageRenderer(client, os.getenv('IMAGE_BASE_URL', '')),
                              PrivateMediaStorage(), image_gate,
                              telemetry=mlflow_tracker.record_image)


def build_media_reader(store):
    return ReadMedia(ImageRepositoryAdapter(store.media_repository()), PrivateMediaStorage())


@dataclass(frozen=True)
class ProductionMediaConfig:
    """Explicit local configuration; nothing is installed or downloaded at runtime."""
    piper_bin: str = "piper"
    piper_model: str = ""
    ffmpeg_bin: str = "ffmpeg"
    media_directory: str = ""

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("ARVOR_PIPER_BIN", "piper"),
                   os.getenv("ARVOR_PIPER_MODEL", ""),
                   os.getenv("ARVOR_FFMPEG_BIN", "ffmpeg"),
                   os.getenv("ARVOR_MEDIA_WORK_DIR", ""))

    def voice_configured(self):
        model = Path(self.piper_model)
        try:
            valid_model = (bool(self.piper_model) and model.is_absolute()
                           and model.suffix.lower() == ".onnx" and not model.is_symlink()
                           and model.is_file() and model.stat().st_size > 0)
        except OSError:
            return False
        return bool(valid_model and shutil.which(self.piper_bin)
                    and shutil.which(self.ffmpeg_bin))

    def video_configured(self):
        return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# One local artefact pipeline at a time: Piper and FFmpeg share the PC CPU.
media_gate = ProductionMediaCapacity()


def build_voice_service(store):
    return GenerateVoice(ProductionMediaAdapter(store.production_media_repository()),
                         production_media, synthesize_voice, media_gate,
                         ProductionMediaConfig.from_environment())


def build_video_service(store):
    return GenerateVideo(ProductionMediaAdapter(store.production_media_repository()),
                         production_media, render, media_gate,
                         ProductionMediaConfig.from_environment(),
                         telemetry=mlflow_tracker.record_video)


def build_media_stream(store):
    return ReadProductionMedia(ProductionMediaAdapter(store.production_media_repository()),
                               production_media)
