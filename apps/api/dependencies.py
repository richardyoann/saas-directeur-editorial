"""Composition root: concrete media adapters are selected only at the API boundary."""
import os
from editorial.media.application import GenerateSceneImage, ReadMedia
from infrastructure.images.sdcpp import PrivateImageRenderer
from infrastructure.media.images import PrivateMediaStorage
from infrastructure.media.capacity import image_gate
from infrastructure.persistence.media_repository import ImageRepositoryAdapter


def build_image_service(store, client):
    return GenerateSceneImage(ImageRepositoryAdapter(store.media_repository()),
                              PrivateImageRenderer(client, os.getenv('IMAGE_BASE_URL', '')),
                              PrivateMediaStorage(), image_gate)


def build_media_reader(store):
    return ReadMedia(ImageRepositoryAdapter(store.media_repository()), PrivateMediaStorage())
