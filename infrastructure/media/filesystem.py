"""Private filesystem paths and exclusive writes, independent of S3 and rendering."""
import os
from pathlib import Path
from uuid import UUID
from editorial.media_rules import MAX_PNG_BYTES, ImageUnavailable, validate_png


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


def write_png(path, data):
    validate_png(data)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return path


def read_png(path):
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
