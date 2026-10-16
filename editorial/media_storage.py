"""Private S3/MinIO storage: immutable objects, bounded IO, no implicit retries."""
import base64
import hashlib
import os
from pathlib import Path
import re
from uuid import UUID
from editorial.runtime_secrets import secret

MAX_FILE_BYTES = 1024 * 1024 * 1024
TYPES = {"image": ("png", "image/png"), "voice": ("wav", "audio/wav"),
         "video": ("mp4", "video/mp4"), "manifest": ("json", "application/json"),
         "subtitles": ("srt", "application/x-subrip")}


class MediaStorageError(Exception):
    pass


def object_key(tenant, run_id, asset_id, kind):
    if kind not in TYPES:
        raise MediaStorageError("media_kind_invalid")
    return f"{UUID(str(tenant))}/{UUID(str(run_id))}/{kind}/{UUID(str(asset_id))}.{TYPES[kind][0]}"


def client():
    # Lazy import: the historical filesystem backend remains independent.
    import boto3
    from botocore.config import Config
    from editorial.visuals import private_image_url
    endpoint = os.getenv("MEDIA_S3_ENDPOINT", "")
    access, secret = secret("MEDIA_S3_ACCESS_KEY"), secret("MEDIA_S3_SECRET_KEY")
    if not private_image_url(endpoint) or not access or not secret:
        raise MediaStorageError("media_configuration_invalid")
    return boto3.client("s3", endpoint_url=endpoint,
                        aws_access_key_id=access, aws_secret_access_key=secret,
                        region_name="us-east-1",
                        config=Config(signature_version="s3v4", connect_timeout=5,
                                      read_timeout=120, retries={"total_max_attempts": 1},
                                      request_checksum_calculation="when_required",
                                      response_checksum_validation="when_required",
                                      proxies={}, s3={"addressing_style": "path"}))


def bucket():
    name = os.getenv("MEDIA_S3_BUCKET", "")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,61}[a-z0-9]", name):
        raise MediaStorageError("media_bucket_invalid")
    return name


def preflight():
    try:
        api, name = client(), bucket()
        api.head_bucket(Bucket=name)
        return api, name
    except Exception:
        raise MediaStorageError("media_storage_unavailable") from None


def put_file(path, tenant, run_id, asset_id, kind):
    """PUT once; a lost acknowledgement is uncertain and must not be replayed."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise MediaStorageError("media_file_invalid")
    api, name = preflight()
    key = object_key(tenant, run_id, asset_id, kind)
    sha, md5, size = hashlib.sha256(), hashlib.md5(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise MediaStorageError("media_file_too_large")
            sha.update(chunk)
            md5.update(chunk)
        if not size:
            raise MediaStorageError("media_file_empty")
        stream.seek(0)
        try:
            result = api.put_object(Bucket=name, Key=key, Body=stream, ContentLength=size,
                                    ContentType=TYPES[kind][1], IfNoneMatch="*",
                                    ContentMD5=base64.b64encode(md5.digest()).decode(),
                                    Metadata={"sha256": sha.hexdigest()})
            reference = {"backend": "minio", "bucket": name, "key": key,
                         "sha256": sha.hexdigest(), "size": size, "kind": kind}
            if result.get("VersionId"):
                reference["version_id"] = result["VersionId"]
            params = {"Bucket": name, "Key": key}
            if reference.get("version_id"):
                params["VersionId"] = reference["version_id"]
            head = api.head_object(**params)
            if head["ContentLength"] != size or head.get("Metadata", {}).get("sha256") != sha.hexdigest():
                raise MediaStorageError("media_integrity_invalid")
            return reference
        except Exception:
            # No DELETE: an object may already exist after a timeout/DB failure.
            raise MediaStorageError("media_upload_uncertain") from None


def get_file(reference, destination, tenant, run_id, asset_id, kind, max_bytes=MAX_FILE_BYTES):
    expected_key = object_key(tenant, run_id, asset_id, kind)
    if (reference.get("backend") != "minio" or reference.get("bucket") != bucket()
            or reference.get("key") != expected_key or reference.get("kind") != kind
            or type(reference.get("size")) is not int or not 0 < reference["size"] <= max_bytes
            or not re.fullmatch(r"[0-9a-f]{64}", reference.get("sha256", ""))):
        raise MediaStorageError("media_reference_invalid")
    destination = Path(destination)
    # Exclusive creation; never touch another invocation's output on failure.
    stream = destination.open("xb")
    body = None
    try:
        params = {"Bucket": reference["bucket"], "Key": expected_key}
        if reference.get("version_id"):
            params["VersionId"] = reference["version_id"]
        response = client().get_object(**params)
        body = response["Body"]
        sha, size = hashlib.sha256(), 0
        if response["ContentLength"] != reference["size"]:
            raise MediaStorageError("media_integrity_invalid")
        with stream:
            while chunk := body.read(1024 * 1024):
                size += len(chunk)
                if size > reference["size"]:
                    raise MediaStorageError("media_integrity_invalid")
                sha.update(chunk)
                stream.write(chunk)
        if size != reference["size"] or sha.hexdigest() != reference["sha256"]:
            raise MediaStorageError("media_integrity_invalid")
    except Exception:
        stream.close()
        destination.unlink(missing_ok=True)
        raise MediaStorageError("media_download_failed") from None
    finally:
        if body is not None:
            body.close()
    return destination
