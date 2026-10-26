"""Host-only trust pins for signing and publication, outside candidate trees."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from scripts.arvor_ci_trust import policy_digest

_ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
DEFAULT_TRUST_PATH = _ACCOUNT_HOME / ".config/arvor-local-ci/trust.json"
REPO = "richardyoann/saas-directeur-editorial"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_FIELDS = frozenset((
    "schema", "repo", "controller_path", "controller_sha",
    "trusted_policy_path", "policy_sha256", "image_id", "key_id",
    "private_key_path", "public_key_path", "public_key_sha256",
    "sent_dir",
))


def _private_regular(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Host trust path cannot be a symlink")
    parent = path.parent
    if parent.is_symlink():
        raise ValueError("Host trust directory cannot be a symlink")
    parent_info = parent.stat()
    if (not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.getuid()
            or stat.S_IMODE(parent_info.st_mode) != 0o700):
        raise ValueError("Host trust directory must be owned and private 0700")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("Host trust file must be owned, regular, private 0600")
    return path.resolve(strict=True)


def load_host_trust(path=DEFAULT_TRUST_PATH):
    """Load strict host pins. Production CLI always uses DEFAULT_TRUST_PATH."""
    path = _private_regular(path)
    raw = path.read_bytes()
    if len(raw) > 32 * 1024:
        raise ValueError("Host trust file too large")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("Unexpected host trust fields")
    if (value["schema"] != "arvor-host-trust-v1" or value["repo"] != REPO
            or not _SHA.fullmatch(value["controller_sha"])
            or not _SHA256.fullmatch(value["policy_sha256"])
            or not _IMAGE.fullmatch(value["image_id"])
            or not _KEY_ID.fullmatch(value["key_id"])
            or not _SHA256.fullmatch(value["public_key_sha256"])):
        raise ValueError("Malformed host trust pins")
    for name in ("controller_path", "trusted_policy_path", "private_key_path",
                 "public_key_path", "sent_dir"):
        candidate = Path(value[name])
        if not candidate.is_absolute() or "\x00" in value[name]:
            raise ValueError("Host trust paths must be absolute")
        value[name] = str(candidate.resolve(strict=False))
    if (Path(value["controller_path"]) == Path(value["trusted_policy_path"])
            or Path(value["sent_dir"]).is_relative_to(Path(value["controller_path"]))):
        raise ValueError("Host trust paths overlap")
    return value


def verify_host_key(trust, public_key_bytes):
    key = serialization.load_pem_public_key(public_key_bytes)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Pinned public key must be Ed25519")
    der = key.public_bytes(serialization.Encoding.DER,
                           serialization.PublicFormat.SubjectPublicKeyInfo)
    actual = hashlib.sha256(der).hexdigest()
    if actual != trust["public_key_sha256"]:
        raise ValueError("Public key fingerprint differs from host trust")


def verify_private_key(trust, private_key_bytes):
    key = serialization.load_pem_private_key(private_key_bytes, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Pinned private key must be Ed25519")
    der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if hashlib.sha256(der).hexdigest() != trust["public_key_sha256"]:
        raise ValueError("Private key does not match host-pinned public key")


def verify_host_controller(trust, controller_path):
    controller = Path(controller_path).resolve(strict=True)
    if str(controller) != trust["controller_path"]:
        raise ValueError("Controller path differs from host trust")
    head = subprocess.check_output(
        ["git", "-C", str(controller), "rev-parse", "HEAD"],
        text=True, timeout=20,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(controller), "status", "--porcelain"],
        text=True, timeout=20,
    ).strip()
    if head != trust["controller_sha"] or dirty:
        raise ValueError("Controller checkout differs from host-pinned clean SHA")
    if policy_digest(controller) != trust["policy_sha256"]:
        raise ValueError("Controller policy digest differs from host trust")
    return controller


def verify_host_signer(trust, signer_path):
    signer = Path(signer_path).resolve(strict=True)
    controller = Path(trust["controller_path"])
    if not signer.is_relative_to(controller):
        raise ValueError("Signer must execute from pinned host controller")
    return signer

