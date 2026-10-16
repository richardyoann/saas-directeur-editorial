"""Visual production contract for the private studio.

Qwen writes the storyboard. A separate, explicitly configured, OpenAI-images-
compatible local service renders PNGs. A server-only, audited request creates
one image for one approved scene; no implicit retries or publication.
"""
import base64
import binascii
import hashlib
import json
import ipaddress
import os
from pathlib import Path
import struct
import tempfile
from urllib.parse import urlsplit
from threading import BoundedSemaphore
from uuid import UUID

import httpx


MAX_PNG_BYTES = 4 * 1024 * 1024
image_gate = BoundedSemaphore(1)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ImageUnavailable(Exception):
    """Absent provider, inaccessible model, invalid/unsafe output or timeout."""

    def __init__(self, code="image_provider_invalid_or_unavailable"):
        self.code = code
        super().__init__(code)


IMAGE_PARAMETERS = {"n": 1, "size": "512x512", "output_format": "png"}


def image_provenance(run, scene_number, prompt):
    """Snapshot what we actually control, without claiming engine telemetry."""
    references = characters(run.get("storyboard") or {})
    canonical = json.dumps(references, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return {"contract_version": "private-image-v2", "provider": "sd.cpp-compatible",
            "parameters": dict(IMAGE_PARAMETERS), "model": None, "seed": None,
            "model_seed_reason": "not_reported_by_image_contract",
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "character_reference_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "character_references": references, "scene_number": scene_number,
            "gpu_verified": False, "vram_peak_bytes": None}


def characters(board):
    """Merge optional Qwen portraits with names used in each scene."""
    entries = {}
    for profile in board.get("cast") or []:
        name = profile["name"].strip()
        key = name.casefold()
        if key not in entries:
            entries[key] = {"name": name, "appearance": profile["appearance"],
                            "personality": profile["personality"], "role": profile["role"],
                            "first_scene": None, "scenes": []}
    for index, scene in enumerate(board.get("scenes", []), 1):
        for raw in scene.get("characters", []):
            name = raw.strip()
            key = name.casefold()
            if key not in entries:
                entries[key] = {"name": name, "appearance": None,
                                "personality": None, "role": None,
                                "first_scene": index, "scenes": []}
            person = entries[key]
            if person["first_scene"] is None:
                person["first_scene"] = index
            if index not in person["scenes"]:
                person["scenes"].append(index)
    return list(entries.values())


def image_prompt(run, scene_number):
    board = run.get("storyboard") or {}
    scenes = board.get("scenes") or []
    if scene_number < 1 or scene_number > len(scenes):
        raise ValueError("invalid_scene_number")
    scene = scenes[scene_number - 1]
    names = ", ".join(scene.get("characters", [])) or "aucun"
    palette = ", ".join(scene.get("colors", []))
    portraits = [
        f"{person['name']} : {person['appearance']}"
        for person in characters(board)
        if person.get("appearance") and any(
            person["name"].casefold() == name.strip().casefold()
            for name in scene.get("characters", [])
        )
    ]
    prompt = (
        "Illustration cinématique cohérente pour une légende bretonne. "
        "Aucune inscription ni texte dans l'image. "
        f"Scène {scene_number} : {scene['title']}. "
        f"Sujet : {scene['visual_description']}. "
        f"Personnages : {names}. "
        f"Repères visuels permanents : {'; '.join(portraits) or 'non définis'}. "
        f"Paysage : {scene['landscape']}. "
        f"Palette : {palette}. "
        f"Cadrage : {scene['shot']}. "
        f"Ambiance : {scene['emotion']}. "
        f"Description artistique : {scene['image_prompt']}."
    )
    if len(prompt) > 14000:
        raise ValueError("image_prompt_too_long")
    return prompt


def validate_png(data):
    """Bound bytes and dimensions before writing user-controlled media."""
    if not isinstance(data, bytes) or len(data) < 45 or len(data) > MAX_PNG_BYTES:
        raise ImageUnavailable()
    if data[:8] != PNG_MAGIC or data[12:16] != b"IHDR" or data[8:12] != b"\x00\x00\x00\r":
        raise ImageUnavailable()
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1 or width > 2048 or height > 2048:
        raise ImageUnavailable()
    return width, height


def private_image_url(value):
    """Only local/private image engines are allowed to receive story prompts."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path.strip("/")):
            return False
        host = parsed.hostname
        if host == "localhost":
            return True
        address = ipaddress.ip_address(host)
        # Explicit loopback/RFC1918/IPv6 ULA allowlist. ipaddress.is_private
        # also includes link-local metadata IPs (169.254.169.254): never
        # allow a prompt to flow to an infrastructure metadata endpoint.
        allowed = (
            "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12",
            "192.168.0.0/16", "::1/128", "fc00::/7",
        )
        return any(address in ipaddress.ip_network(net) for net in allowed)
    except ValueError:
        return False


async def render_png(client: httpx.AsyncClient, base_url: str, prompt: str):
    if not private_image_url(base_url):
        raise ImageUnavailable()
    try:
        response = await client.post(
            base_url.rstrip("/") + "/v1/images/generations",
            json={"prompt": prompt, **IMAGE_PARAMETERS},
            timeout=120.0
        )
        if response.status_code >= 500:
            raise ImageUnavailable("image_provider_response_uncertain")
        if response.status_code != 200:
            raise ImageUnavailable("image_provider_rejected")
        if len(response.content) > MAX_PNG_BYTES * 2:
            raise ImageUnavailable()
        payload = response.json()
        entries = payload.get("data") if isinstance(payload, dict) else None
        encoded = entries[0].get("b64_json") if isinstance(entries, list) and len(entries) == 1 and isinstance(entries[0], dict) else None
        if not isinstance(encoded, str) or len(encoded) > MAX_PNG_BYTES * 2:
            raise ImageUnavailable()
        data = base64.b64decode(encoded, validate=True)
        validate_png(data)
        return data
    except httpx.TimeoutException:
        raise ImageUnavailable("image_provider_timeout") from None
    except httpx.HTTPError:
        raise ImageUnavailable("image_provider_response_uncertain") from None
    except (ValueError, KeyError, TypeError, binascii.Error):
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
            recovery.unlink()
            return reference
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

