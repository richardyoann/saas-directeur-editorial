"""External credentials: environment, NAME_FILE, or systemd LoadCredential.

Values are never logged. Missing, malformed and ambiguous sources fail closed.
No secret is cached by the module, allowing a controlled rotation.
"""
import os
from pathlib import Path
import stat

MAX_SECRET_BYTES = 16384


def secret_from_sources(name: str, values=None, credentials_directory=None) -> str:
    if not isinstance(name, str) or not name.isidentifier():
        return ""
    if values is None:
        values = os.environ
    direct = values.get(name) or ""
    filename = values.get(name + "_FILE") or ""
    if direct and filename:
        return ""
    if direct:
        return direct if isinstance(direct, str) and not any(c in direct for c in "\r\n\x00") else ""
    if not filename:
        base = credentials_directory if credentials_directory is not None else values.get("CREDENTIALS_DIRECTORY", "")
        if base:
            filename = str(Path(base) / name)
    if not isinstance(filename, str) or not filename:
        return ""
    try:
        path = Path(filename)
        if not path.is_absolute() or path.is_symlink():
            return ""
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SECRET_BYTES:
            return ""
        with path.open("rb") as handle:
            raw = handle.read(MAX_SECRET_BYTES + 1)
        if len(raw) > MAX_SECRET_BYTES:
            return ""
        value = raw.decode("utf-8").rstrip("\r\n")
        if not value or any(c in value for c in "\r\n\x00"):
            return ""
        return value
    except (OSError, ValueError, UnicodeDecodeError):
        return ""


def secret(name: str) -> str:
    return secret_from_sources(name)
