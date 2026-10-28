"""Load the private MLflow client configuration into an Arvor process.

The client environment file is produced by
``scripts/provision_mlflow_local.py`` outside the repository, with mode
``0600``.  Loading it is explicit: the caller exports
``ARVOR_MLFLOW_ENV_FILE`` and the process calls
:func:`load_client_environment` once at startup.

Design rules:

* every value already present in the process environment wins, so an operator
  can override a single setting without editing the private file;
* only a strict allow-list of keys is copied, so an unrelated ``.env`` entry
  can never become telemetry configuration;
* the file must be a regular file owned by the current user with mode
  ``0600``; symlinks and group/world-readable files are refused;
* a configured CA bundle must be an existing, non-symlink regular file;
* the result contains counts and booleans only, never a secret value.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

MAX_ENV_BYTES = 16 * 1024

ALLOWED_KEYS = frozenset({
    "ARVOR_MLFLOW_ENABLED",
    "MLFLOW_TRACKING_URI",
    "MLFLOW_TRACKING_USERNAME",
    "MLFLOW_TRACKING_PASSWORD",
    "ARVOR_MLFLOW_SPOOL",
    "MLFLOW_HTTP_REQUEST_TIMEOUT",
    "MLFLOW_HTTP_REQUEST_MAX_RETRIES",
    "REQUESTS_CA_BUNDLE",
    "AWS_CA_BUNDLE",
})
CA_KEYS = frozenset({"REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE"})


class ClientEnvironmentError(ValueError):
    """A private client file cannot be trusted; the message is a fixed code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _validate_ca(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ClientEnvironmentError("ca_bundle_invalid")
    try:
        info = path.stat()
    except OSError:
        raise ClientEnvironmentError("ca_bundle_invalid") from None
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.R_OK):
        raise ClientEnvironmentError("ca_bundle_invalid")
    return str(path)


def _parse(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in ALLOWED_KEYS:
            continue
        if not value or any(ord(char) < 32 for char in value):
            raise ClientEnvironmentError("env_value_invalid")
        if key in CA_KEYS:
            value = _validate_ca(value)
        values[key] = value
    return values


def load_client_environment(path, environ=None):
    """Merge an allow-listed private file into ``environ`` without overriding.

    Returns ``{"loaded": n, "kept": n}``; it never returns a value and never
    writes to a log.  Raises :class:`ClientEnvironmentError` on an untrusted
    file so a caller can decide whether telemetry stays disabled.
    """
    source = Path(path)
    if source.is_symlink():
        raise ClientEnvironmentError("env_file_symlink")
    try:
        info = source.stat()
    except OSError:
        raise ClientEnvironmentError("env_file_unreadable") from None
    if not stat.S_ISREG(info.st_mode):
        raise ClientEnvironmentError("env_file_not_regular")
    if info.st_uid != os.geteuid():
        raise ClientEnvironmentError("env_file_owner")
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ClientEnvironmentError("env_file_permissions")
    if info.st_size > MAX_ENV_BYTES:
        raise ClientEnvironmentError("env_file_too_large")
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ClientEnvironmentError("env_file_unreadable") from None
    values = _parse(text)
    target = os.environ if environ is None else environ
    loaded = kept = 0
    for key, value in values.items():
        if key in target:
            kept += 1
            continue
        target[key] = value
        loaded += 1
    return {"loaded": loaded, "kept": kept}
