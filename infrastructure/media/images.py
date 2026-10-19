"""Configured image storage adapter with explicit post-commit recovery cleanup."""
import os
from pathlib import Path
from typing import cast
import tempfile
from editorial.media.contracts import StoredAsset
from editorial.media_rules import MAX_PNG_BYTES, ImageUnavailable, validate_png
from infrastructure.media.filesystem import media_location, read_png, write_png


def save_png(tenant, run_id, scene_id, data):
    validate_png(data)
    if os.getenv("EDITORIAL_MEDIA_BACKEND", "filesystem") == "minio":
        from infrastructure.media.s3 import put_file, MediaStorageError
        # Keep the generated PNG on an uncertain upload. It must not require
        # another model call merely because storage lost its acknowledgement.
        recovery = media_location(tenant, run_id, scene_id)
        try:
            write_png(recovery, data)
            reference = put_file(recovery, tenant, run_id, scene_id, "image")
            # The API removes this recovery file only after PostgreSQL confirms
            # the storage reference. A lost DB acknowledgement must preserve it.
            return reference, recovery
        except (MediaStorageError, OSError):
            raise ImageUnavailable("image_storage_result_uncertain") from None
    path = media_location(tenant, run_id, scene_id)
    try:
        return write_png(path, data)
    except OSError:
        raise ImageUnavailable() from None


def load_png(tenant, run_id, scene_id, storage=None):
    if storage:
        from infrastructure.media.s3 import get_file, MediaStorageError
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = get_file(storage, Path(directory) / "image.png", tenant,
                                run_id, scene_id, "image", max_bytes=MAX_PNG_BYTES)
                data = path.read_bytes()
                validate_png(data)
                return data
        except (MediaStorageError, OSError):
            raise ImageUnavailable("image_storage_unavailable") from None
    return read_png(media_location(tenant, run_id, scene_id))


def media_preflight(tenant, run_id, scene_id):
    backend = os.getenv("EDITORIAL_MEDIA_BACKEND", "filesystem")
    if backend == "filesystem":
        return media_location(tenant, run_id, scene_id)
    if backend == "minio":
        from infrastructure.media.s3 import preflight, MediaStorageError
        try:
            media_location(tenant, run_id, scene_id)
            preflight()
            return None
        except MediaStorageError:
            raise ImageUnavailable("image_storage_unavailable") from None
    raise ImageUnavailable("image_storage_configuration_invalid")


class PrivateMediaStorage:
    def preflight(self, tenant, run_id, scene_id):
        media_preflight(tenant, run_id, scene_id)

    def save(self, tenant, run_id, scene_id, data):
        saved = save_png(tenant, run_id, scene_id, data)
        return StoredAsset(*saved) if isinstance(saved, tuple) else StoredAsset(None, None)

    def load(self, tenant, run_id, scene_id, reference=None):
        return load_png(tenant, run_id, scene_id, reference)

    def acknowledge(self, receipt):
        if receipt.recovery is not None:
            cast(Path, receipt.recovery).unlink()
