"""Visual production contract for the private studio.

Qwen writes the storyboard. A separate, explicitly configured, OpenAI-images-
compatible local service renders PNGs. A server-only, audited request creates
one image for one approved scene; no implicit retries or publication.
"""
import asyncio
import base64
import binascii
import json
import os
from pathlib import Path
import tempfile
from threading import BoundedSemaphore
from uuid import UUID

import httpx

# Re-export the historical public API; exception and constant identities are shared.
from editorial.media_rules import (
    MAX_PNG_BYTES, PNG_MAGIC, IMAGE_PARAMETERS, ImageUnavailable, ImagePromptTooLong,
    characters, image_prompt, image_provenance, validate_png, private_image_url,
)


image_gate = BoundedSemaphore(1)


async def render_png(client: httpx.AsyncClient, base_url: str, prompt: str):
    if not private_image_url(base_url):
        raise ImageUnavailable()
    try:
        async with asyncio.timeout(120):
            async with client.stream(
                "POST", base_url.rstrip("/") + "/v1/images/generations",
                json={"prompt": prompt, **IMAGE_PARAMETERS},
                timeout=120.0, follow_redirects=False
            ) as response:
                if response.status_code >= 500:
                    raise ImageUnavailable("image_provider_response_uncertain")
                if response.status_code != 200:
                    raise ImageUnavailable("image_provider_rejected")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_PNG_BYTES * 2:
                        raise ImageUnavailable()
                    body.extend(chunk)
                payload = json.loads(body)
        entries = payload.get("data") if isinstance(payload, dict) else None
        encoded = entries[0].get("b64_json") if isinstance(entries, list) and len(entries) == 1 and isinstance(entries[0], dict) else None
        if not isinstance(encoded, str) or len(encoded) > MAX_PNG_BYTES * 2:
            raise ImageUnavailable()
        data = base64.b64decode(encoded, validate=True)
        validate_png(data)
        return data
    except (httpx.TimeoutException, TimeoutError):
        raise ImageUnavailable("image_provider_timeout") from None
    except httpx.HTTPError:
        raise ImageUnavailable("image_provider_response_uncertain") from None
    except (ValueError, KeyError, TypeError, binascii.Error, RecursionError):
        raise ImageUnavailable() from None


def media_location(tenant: UUID, run_id: UUID, scene_id: UUID):
    """Never derive any storage path from a prompt or externally supplied name."""
    raw = os.getenv("EDITORIAL_MEDIA_ROOT", "")
    root = Path(raw)
    if not raw or not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ImageUnavailable()
    parent = root / str(tenant) / str(run_id)
    if parent.is_symlink() or parent.parent.is_symlink():
        raise ImageUnavailable()
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return parent / (str(scene_id) + ".png")


def save_png(tenant, run_id, scene_id, data):
    validate_png(data)
    if os.getenv("EDITORIAL_MEDIA_BACKEND", "filesystem") == "minio":
        from editorial.media_storage import put_file, MediaStorageError
        # Keep the generated PNG on an uncertain upload. It must not require
        # another model call merely because storage lost its acknowledgement.
        recovery = media_location(tenant, run_id, scene_id)
        try:
            with recovery.open("xb") as handle:
                handle.write(data)
            reference = put_file(recovery, tenant, run_id, scene_id, "image")
            # The API removes this recovery file only after PostgreSQL confirms
            # the storage reference. A lost DB acknowledgement must preserve it.
            return reference, recovery
        except (MediaStorageError, OSError):
            raise ImageUnavailable("image_storage_result_uncertain") from None
    path = media_location(tenant, run_id, scene_id)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except (FileExistsError, OSError):
        raise ImageUnavailable() from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except OSError:
        path.unlink(missing_ok=True)
        raise ImageUnavailable() from None
    return path


def load_png(tenant, run_id, scene_id, storage=None):
    if storage:
        from editorial.media_storage import get_file, MediaStorageError
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = get_file(storage, Path(directory) / "image.png", tenant,
                                run_id, scene_id, "image", max_bytes=MAX_PNG_BYTES)
                data = path.read_bytes()
                validate_png(data)
                return data
        except (MediaStorageError, OSError):
            raise ImageUnavailable("image_storage_unavailable") from None
    path = media_location(tenant, run_id, scene_id)
    if path.is_symlink() or not path.is_file():
        raise ImageUnavailable()
    try:
        if path.stat().st_size > MAX_PNG_BYTES:
            raise ImageUnavailable()
        data = path.read_bytes()
        validate_png(data)
        return data
    except OSError:
        raise ImageUnavailable() from None


def media_preflight(tenant, run_id, scene_id):
    backend = os.getenv("EDITORIAL_MEDIA_BACKEND", "filesystem")
    if backend == "filesystem":
        return media_location(tenant, run_id, scene_id)
    if backend == "minio":
        from editorial.media_storage import preflight, MediaStorageError
        try:
            media_location(tenant, run_id, scene_id)
            preflight()
            return None
        except MediaStorageError:
            raise ImageUnavailable("image_storage_unavailable") from None
    raise ImageUnavailable("image_storage_configuration_invalid")

