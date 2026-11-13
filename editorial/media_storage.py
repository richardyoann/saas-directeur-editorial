"""Compatibility exports for the private S3 adapter."""
from infrastructure.media.s3 import (  # noqa: F401  (re-export intentionnel)
    MAX_FILE_BYTES, TYPES, MediaStorageError, object_key, client, bucket,
    preflight, put_file, get_file,
)
