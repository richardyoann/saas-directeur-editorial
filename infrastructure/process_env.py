"""Minimal child-process environment for media and rendering binaries.

Arvor never copies telemetry or application credentials into ``os.environ``
itself, but an operator can supply them through the process environment. Any
subprocess (Piper, FFmpeg) must therefore receive a filtered copy: these tools
have no legitimate need for tracing or storage secrets.
"""
import os

SECRET_PREFIXES = ("MLFLOW_", "ARVOR_MLFLOW_", "AWS_", "ARVOR_MINIO_")
SECRET_KEYS = frozenset({
    "EDITORIAL_API_TOKEN",
    "EDITORIAL_WEB_PASSWORD",
    "PGPASSWORD",
    "DATABASE_URL",
    "PO_DATABASE_URL",
    "PO_TEST_DATABASE_URL",
    "TRACE_TEST_DATABASE_URL",
})


def child_environment():
    """Return an environment copy without credentials inherited by media tools."""
    return {key: value for key, value in os.environ.items()
            if key not in SECRET_KEYS and not key.startswith(SECRET_PREFIXES)}
