"""Build-time PyPI vulnerability snapshot + strict, network-free runtime verification.

The trusted Docker image runs --build with internet access and immutable Python
environments. The isolated PR sandbox uses ONLY --verify; it cannot refresh the
snapshot, make network calls, install packages, or ignore a vulnerability.
The image must be rebuilt if the 24-hour snapshot expires.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path("/opt/arvor/security")
MANIFEST = ROOT / "manifest.json"
MAX_AGE = timedelta(hours=24)
SERVICE = "pypi"
EXPECTED_AUDITOR = "2.10.1"
STATUS_CODES = {"OK", "VULNERABLE", "PREUVE_PERIMEE", "PREUVE_NON_CORRESPONDANTE", "RECONSTRUCTION_IMAGE_REQUISE", "ERREUR_INFRA"}


class AuditError(ValueError):
    def __init__(self, code, message):
        if code not in STATUS_CODES:
            raise ValueError("Unrecognized audit status code")
        self.code = code
        super().__init__(message)


def digest_packages(packages):
    canonical = json.dumps(packages, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def installed_auditor_version(python):
    code = "from importlib.metadata import version; print(version('pip-audit'))"
    return subprocess.check_output([python, "-c", code], text=True, timeout=15).strip()
VERSIONS = ("312", "314")
PYTHONS = {v: f"/opt/arvor/py{v}/bin/python" for v in VERSIONS}
INVENTORY_CODE = """
import json
from importlib.metadata import distributions
installed = []
for dist in distributions():
    name = dist.metadata.get("Name")
    if not name or not dist.version:
        raise SystemExit("Unidentified installed distribution")
    installed.append([name, dist.version])
print(json.dumps(installed))
"""


def normalize(name):
    if not isinstance(name, str) or not name:
        raise ValueError("Missing distribution name")
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_packages(python):
    result = subprocess.run(
        [python, "-c", INVENTORY_CODE], capture_output=True, text=True,
        check=True, timeout=25,
    )
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Empty Python environment")
    packages = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("Malformed package inventory")
        name, version = row
        key = normalize(name)
        if not isinstance(version, str) or not version or key in packages:
            raise ValueError("Invalid or duplicate installed distribution")
        packages[key] = version
    return packages


def audited_packages(report):
    deps = report.get("dependencies") if isinstance(report, dict) else report
    if not isinstance(deps, list) or not deps:
        raise AuditError("PREUVE_NON_CORRESPONDANTE", "Missing pip-audit dependency results")
    packages = {}
    for dep in deps:
        if not isinstance(dep, dict):
            raise AuditError("PREUVE_NON_CORRESPONDANTE", "Invalid audit entry")
        name = normalize(dep.get("name"))
        version = dep.get("version")
        if not isinstance(version, str) or not version or name in packages:
            raise AuditError("PREUVE_NON_CORRESPONDANTE", "Duplicate or unversioned audited package")
        if "skip_reason" in dep and dep["skip_reason"] is not None:
            raise AuditError("PREUVE_NON_CORRESPONDANTE", "Auditor skipped dependency: " + name)
        if dep.get("vulns") != []:
            raise AuditError("VULNERABLE", "Vulnerable or unaudited dependency: " + name)
        packages[name] = version
    return packages


def snapshot_file(version):
    return ROOT / ("pip-audit-py" + version + ".json")


def read_snapshot(version, expected_hash):
    data = snapshot_file(version).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise AuditError("PREUVE_NON_CORRESPONDANTE", "Audit snapshot integrity mismatch: " + version)
    return audited_packages(json.loads(data))


def build():
    """Fetch vulnerability intelligence on an explicitly networked trusted build."""
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "arvor-ci-audit-v1", "created_at": None,
        "service": SERVICE, "versions": {}
    }
    # New ephemeral cache per security build: NEVER reuse yesterday's HTTP
    # responses, and never treat HTTP caching as an offline vulnerability DB.
    with tempfile.TemporaryDirectory(prefix="arvor-pypi-fresh-") as cache:
        for version in VERSIONS:
            python = PYTHONS[version]
            auditor = installed_auditor_version(python)
            if auditor != EXPECTED_AUDITOR:
                raise AuditError("PREUVE_NON_CORRESPONDANTE",
                                 "Unexpected pip-audit version: " + version)
            dest = snapshot_file(version)
            cmd = [
                python, "-m", "pip_audit", "--local", "--strict",
                "--vulnerability-service", SERVICE,
                "--format", "json", "--desc", "off", "--aliases", "off",
                "--progress-spinner", "off",
                "--cache-dir", cache, "--output", str(dest)
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  check=False, timeout=300)
            if proc.returncode != 0:
                # A genuine vulnerability may still generate a complete JSON
                # report. Distinguish this from DNS, timeouts or broken PyPI.
                if dest.exists():
                    try:
                        audited_packages(json.loads(dest.read_text(encoding="utf-8")))
                    except AuditError as error:
                        raise error from None
                    except (ValueError, json.JSONDecodeError):
                        pass
                raise AuditError("ERREUR_INFRA",
                                 "PyPI audit could not complete; no PASS evidence")
            data = dest.read_bytes()
            audit = audited_packages(json.loads(data))
            inventory = installed_packages(python)
            if inventory != audit:
                raise AuditError("PREUVE_NON_CORRESPONDANTE",
                                 "Audited packages differ from installed environment " + version)
            manifest["versions"][version] = {
                "snapshot_sha256": hashlib.sha256(data).hexdigest(),
                "inventory_sha256": digest_packages(inventory),
                "pip_audit_version": auditor,
                "packages": inventory,
            }
    manifest["created_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    print("ARVOR_AUDIT_STATUS=OK")
    print("BUILD AUDIT OK: full environments audited via fresh PyPI responses")


def verify():
    """Offline verification of the immutable evidence baked into the image."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict)
            or manifest.get("schema") != "arvor-ci-audit-v1"
            or manifest.get("service") != SERVICE
            or set(manifest.get("versions", {})) != set(VERSIONS)):
        raise AuditError("PREUVE_NON_CORRESPONDANTE",
                         "Incomplete or unsupported audit manifest")
    created = datetime.fromisoformat(manifest["created_at"])
    if created.tzinfo is None:
        raise AuditError("PREUVE_NON_CORRESPONDANTE", "Naive audit timestamp")
    age = datetime.now(timezone.utc) - created
    if age < -timedelta(minutes=2) or age > MAX_AGE:
        raise AuditError("PREUVE_PERIMEE",
                         "Security audit expired: rebuild the trusted image")
    for version in VERSIONS:
        record = manifest["versions"][version]
        auditor = installed_auditor_version(PYTHONS[version])
        if (record.get("pip_audit_version") != EXPECTED_AUDITOR
                or auditor != EXPECTED_AUDITOR):
            raise AuditError("PREUVE_NON_CORRESPONDANTE",
                             "Auditor version mismatch: " + version)
        inventory = installed_packages(PYTHONS[version])
        if (inventory != record["packages"]
                or digest_packages(inventory) != record["inventory_sha256"]):
            raise AuditError("PREUVE_NON_CORRESPONDANTE",
                             "Installed inventory changed: " + version)
        audit = read_snapshot(version, record["snapshot_sha256"])
        if audit != inventory:
            raise AuditError("PREUVE_NON_CORRESPONDANTE",
                             "Vulnerability snapshot does not cover installed packages: " + version)
    print("ARVOR_AUDIT_STATUS=OK")
    print("OFFLINE DEPENDENCY AUDIT OK: 3.12 and 3.14; fresh complete PyPI snapshots; "
          f"age={int(age.total_seconds())}s / max={int(MAX_AGE.total_seconds())}s")


def main():
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = p.parse_args()
    try:
        if args.build:
            build()
        else:
            verify()
        return 0
    except AuditError as exc:
        print("ARVOR_AUDIT_STATUS=" + exc.code, file=sys.stderr)
        print("DEPENDENCY AUDIT BLOCKED: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError) as exc:
        print("ARVOR_AUDIT_STATUS=ERREUR_INFRA", file=sys.stderr)
        print("DEPENDENCY AUDIT BLOCKED: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
