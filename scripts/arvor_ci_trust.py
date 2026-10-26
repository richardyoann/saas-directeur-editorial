"""Trust policy shared by the pinned host controller, never by candidate code."""
import hashlib
import json
from pathlib import Path

POLICY_VERSION = "arvor-local-ci-policy-v2"
# This inventory is versioned with the reviewed controller. Its own file hash is
# part of the digest, so changing the inventory changes the pinned policy ID.
SANDBOX_POLICY_FILES = (
    "arvor_local_ci.py",
    "arvor_ci_gate.py",
    "arvor_ci_trusted_unittest.py",
    "arvor_ci_supervised_entrypoint.sh",
    "arvor_ci_trusted_gitleaks.toml",
    "arvor_ci_trusted_gitleaksignore",
)

POLICY_FILES = (
    "scripts/arvor_ci_trust.py",
    "scripts/arvor_local_ci.py",
    "scripts/arvor_ci_gate.py",
    "scripts/arvor_ci_trusted_unittest.py",
    "scripts/arvor_ci_supervised_entrypoint.sh",
    "scripts/arvor_ci_trusted_gitleaks.toml",
    "scripts/arvor_ci_trusted_gitleaksignore",
    "scripts/arvor_ci_host_supervisor.py",
    "scripts/arvor_ci_evidence_verify.py",
    "scripts/arvor_ci_attestation.py",
    "scripts/arvor_ci_host_trust.py",
    "scripts/arvor_ci_publish.py",
    "scripts/arvor_ci_merge.py",
    "ci/local/Dockerfile",
    "ci/local/requirements-ci.txt",
    "scripts/run_regression.py",
    "scripts/prepare_test_database.py",
    "scripts/benchmark_editorial_sql.py",
    "scripts/ci_policy.py",
    "scripts/ci_autonomy.py",
    "scripts/arvor_ci_sandbox.py",
    "scripts/arvor_ci_entrypoint.sh",
    "AGENTS.md",
    "docs/mco/OPS_LOCAL_CI_RUNBOOK.md",
    "docs/mco/OPS_LOCAL_CI_FINALIZATION_20261026.md",
    "docs/mco/OPS_LOCAL_CI_MIGRATION_20261022.md",
    ".github/workflows/local-delivery.yml",
    ".github/workflows/regression.yml",
    ".github/workflows/secret-scan.yml",
    ".github/workflows/security-deps.yml",
    ".github/workflows/studio-browser.yml",
    ".github/workflows/ci-policy.yml",
    ".github/workflows/ci-risk-review.yml",
    ".github/workflows/ci-status-report.yml",
    ".github/workflows/ci-annotations.yml",
    ".github/workflows/chat-approved-delivery.yml",
)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def policy_snapshot(root):
    root = Path(root).resolve(strict=True)
    hashes = {}
    for relative in POLICY_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("Trusted policy file missing or linked: " + relative)
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def policy_digest(root):
    return hashlib.sha256(canonical_json({
        "version": POLICY_VERSION,
        "files": policy_snapshot(root),
    })).hexdigest()


def validate_docker_inspection(obj, checkout, trusted, image):
    """Validate the host-captured Docker inspect document, not receipt booleans."""
    if not isinstance(obj, dict):
        raise ValueError("Malformed host Docker observation")
    host = obj.get("HostConfig") or {}
    config = obj.get("Config") or {}
    if (obj.get("Image") != image or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is True
            or "ALL" not in [str(x).upper() for x in (host.get("CapDrop") or [])]
            or not any(str(x).lower() in ("no-new-privileges", "no-new-privileges:true")
                       for x in (host.get("SecurityOpt") or []))
            or str(config.get("User")) != "999:999"):
        raise ValueError("Docker observation violates pinned isolation policy")
    options = [str(x).lower() for x in (host.get("SecurityOpt") or [])]
    if (host.get("CapAdd") or host.get("Devices") or host.get("PortBindings")
            or host.get("PidMode") == "host" or host.get("IpcMode") == "host"
            or any(x in ("seccomp=unconfined", "apparmor=unconfined") for x in options)):
        raise ValueError("Docker observation contains an escape configuration")
    mounts = obj.get("Mounts")
    if not isinstance(mounts, list):
        raise ValueError("Docker observation has no mount list")
    allowed_tmpfs = {"/tmp", "/var/lib/postgresql/data", "/run/postgresql"}
    for mount in mounts:
        destination = mount.get("Destination")
        if mount.get("Type") == "tmpfs" and destination in allowed_tmpfs:
            continue
        if mount.get("Type") != "bind" or destination not in ("/workspace", "/trusted"):
            raise ValueError("Unapproved Docker mount or volume")
    binds = {m["Destination"]: m for m in mounts if m.get("Type") == "bind"}
    if set(binds) != {"/workspace", "/trusted"}:
        raise ValueError("Docker observation has missing or extra binds")
    for dst, expected in (("/workspace", checkout), ("/trusted", trusted)):
        mount = binds[dst]
        if (Path(mount["Source"]).resolve() != Path(expected).resolve()
                or mount.get("RW") is not False):
            raise ValueError("Candidate and policy binds must be read-only")
    return True
