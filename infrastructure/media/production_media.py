"""Private storage adapter for voice, video and subtitle production files.

The MinIO backend is used only when ``EDITORIAL_MEDIA_BACKEND=minio``; the
default filesystem backend keeps local development possible without S3. Every
reference is tenant/run scoped and re-validated on read.
"""
import hashlib
import os
from pathlib import Path
import re
from uuid import UUID

SUFFIXES = {"voice": ".wav", "video": ".mp4", "subtitles": ".srt",
            "image": ".png"}
MAX_BYTES = {"voice": 64 * 1024 * 1024, "video": 512 * 1024 * 1024,
             "subtitles": 1024 * 1024, "image": 32 * 1024 * 1024}
SAVED_KINDS = frozenset({"voice", "video", "subtitles"})
MAX_DOWNLOAD = 512 * 1024 * 1024


class ProductionStorageError(Exception):
    pass


def backend():
    value = os.getenv("EDITORIAL_MEDIA_BACKEND", "filesystem")
    if value not in {"filesystem", "minio"}:
        raise ProductionStorageError("production_storage_configuration_invalid")
    return value


def _root():
    raw = os.getenv("EDITORIAL_MEDIA_ROOT", "")
    root = Path(raw)
    if not raw or not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ProductionStorageError("production_storage_unavailable")
    return root


def _validate_input(path, kind):
    path = Path(path)
    if kind not in SAVED_KINDS or path.suffix.lower() != SUFFIXES[kind]:
        raise ProductionStorageError("production_media_kind_invalid")
    if path.is_symlink() or not path.is_file():
        raise ProductionStorageError("production_media_file_invalid")
    size = path.stat().st_size
    if not 0 < size <= MAX_BYTES[kind]:
        raise ProductionStorageError("production_media_size_invalid")
    return size


def save(path, tenant, run_id, asset_id, kind):
    """Copy one local file into private storage and return a validated reference."""
    path = Path(path)
    size = _validate_input(path, kind)
    if backend() == "minio":
        from infrastructure.media.s3 import MediaStorageError, put_file
        try:
            return put_file(path, tenant, run_id, asset_id, kind)
        except MediaStorageError:
            raise ProductionStorageError("production_storage_unavailable") from None
    root = _root()
    parent = root / str(UUID(str(tenant))) / str(UUID(str(run_id))) / "production"
    if parent.is_symlink() or parent.parent.is_symlink():
        raise ProductionStorageError("production_storage_unavailable")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = parent / (str(UUID(str(asset_id))) + SUFFIXES[kind])
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    digest = digest.hexdigest()
    try:
        fd = os.open(destination, flags, 0o600)
        with os.fdopen(fd, "wb") as output, path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
    except OSError:
        destination.unlink(missing_ok=True)
        raise ProductionStorageError("production_storage_unavailable") from None
    return {"backend": "filesystem", "key": str(destination), "kind": kind,
            "sha256": digest, "size": size}


def _local_path(reference, tenant, run_id, asset_id, kind):
    root = _root()
    expected = (root / str(UUID(str(tenant))) / str(UUID(str(run_id))) / "production"
                / (str(UUID(str(asset_id))) + SUFFIXES[kind]))
    key = reference.get("key")
    if key != str(expected):
        raise ProductionStorageError("production_reference_invalid")
    path = Path(key)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ProductionStorageError("production_reference_invalid")
    if not path.is_file():
        raise ProductionStorageError("production_storage_unavailable")
    return path


def _load_image(reference, destination, tenant, run_id, asset_id, max_bytes):
    """Images are written by the image adapter (MinIO dict or private file path)."""
    destination = Path(destination)
    if any(part.is_symlink() for part in destination.parents):
        raise ProductionStorageError("production_storage_unavailable")
    if isinstance(reference, dict):
        if reference.get("kind") != "image" or reference.get("backend") != "minio":
            raise ProductionStorageError("production_reference_invalid")
        if backend() != "minio":
            raise ProductionStorageError("production_reference_invalid")
        from infrastructure.media.s3 import MediaStorageError, get_file
        try:
            return get_file(reference, Path(destination), tenant, run_id, asset_id,
                            "image", max_bytes=min(max_bytes, MAX_BYTES["image"]))
        except MediaStorageError:
            raise ProductionStorageError("production_storage_unavailable") from None
    root = _root()
    expected = (root / str(UUID(str(tenant))) / str(UUID(str(run_id)))
                / (str(UUID(str(asset_id))) + ".png"))
    if not isinstance(reference, str) or reference != str(expected):
        raise ProductionStorageError("production_reference_invalid")
    path = Path(reference)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ProductionStorageError("production_reference_invalid")
    if not path.is_file() or not 0 < path.stat().st_size <= min(max_bytes, MAX_BYTES["image"]):
        raise ProductionStorageError("production_reference_invalid")
    try:
        with path.open("rb") as reader, Path(destination).open("xb") as output:
            while chunk := reader.read(1024 * 1024):
                output.write(chunk)
    except OSError:
        Path(destination).unlink(missing_ok=True)
        raise ProductionStorageError("production_storage_unavailable") from None
    return Path(destination)


def load(reference, destination, tenant, run_id, asset_id, kind, max_bytes=MAX_DOWNLOAD):
    """Copy one stored object to an exclusive local destination after integrity checks."""
    if kind == "image":
        return _load_image(reference, destination, tenant, run_id, asset_id, max_bytes)
    if kind not in SAVED_KINDS or not isinstance(reference, dict):
        raise ProductionStorageError("production_reference_invalid")
    if (reference.get("kind") != kind
            or type(reference.get("size")) is not int
            or not 0 < reference["size"] <= min(max_bytes, MAX_BYTES[kind])
            or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("sha256", "")))):
        raise ProductionStorageError("production_reference_invalid")
    destination = Path(destination)
    # Never write through a symlinked temporary directory component.
    if any(part.is_symlink() for part in destination.parents):
        raise ProductionStorageError("production_storage_unavailable")
    if backend() == "minio" and reference.get("backend") == "minio":
        from infrastructure.media.s3 import MediaStorageError, get_file
        try:
            return get_file(reference, destination, tenant, run_id, asset_id, kind,
                            max_bytes=min(max_bytes, MAX_BYTES[kind]))
        except MediaStorageError:
            raise ProductionStorageError("production_storage_unavailable") from None
    if reference.get("backend") != "filesystem":
        raise ProductionStorageError("production_reference_invalid")
    source = _local_path(reference, tenant, run_id, asset_id, kind)
    if source.stat().st_size != reference["size"]:
        raise ProductionStorageError("production_integrity_invalid")
    sha, size = hashlib.sha256(), 0
    try:
        with source.open("rb") as reader, destination.open("xb") as output:
            while chunk := reader.read(1024 * 1024):
                size += len(chunk)
                if size > reference["size"]:
                    raise ProductionStorageError("production_integrity_invalid")
                sha.update(chunk)
                output.write(chunk)
    except OSError:
        destination.unlink(missing_ok=True)
        raise ProductionStorageError("production_storage_unavailable") from None
    if size != reference["size"] or sha.hexdigest() != reference["sha256"]:
        destination.unlink(missing_ok=True)
        raise ProductionStorageError("production_integrity_invalid")
    return destination


def open_reference(reference, tenant, run_id, media_id, kind, max_bytes=MAX_DOWNLOAD):
    """Materialise a stored object in a private temporary file for streaming."""
    import tempfile
    directory = tempfile.TemporaryDirectory(prefix="arvor-media-")
    return load(reference, Path(directory.name) / ("media" + SUFFIXES[kind]),
                tenant, run_id, media_id, kind, max_bytes=max_bytes), directory
