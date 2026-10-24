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

ROOT = Path("/opt/arvor/security")
MANIFEST = ROOT / "manifest.json"
MAX_AGE = timedelta(hours=24)
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
        raise ValueError("Missing pip-audit dependency results")
    packages = {}
    for dep in deps:
        if not isinstance(dep, dict):
            raise ValueError("Invalid audit entry")
        name = normalize(dep.get("name"))
        version = dep.get("version")
        if not isinstance(version, str) or not version or name in packages:
            raise ValueError("Duplicate or unversioned audited package")
        if dep.get("skip_reason") or dep.get("vulns") != []:
            raise ValueError("Vulnerable or skipped dependency: " + name)
        packages[name] = version
    return packages


def snapshot_file(version):
    return ROOT / ("pip-audit-py" + version + ".json")


def read_snapshot(version, expected_hash):
    data = snapshot_file(version).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError("Audit snapshot integrity mismatch: " + version)
    return audited_packages(json.loads(data))


def build():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "arvor-ci-audit-v1", "created_at": None,
                "service": "pypi", "versions": {}}
    for version in VERSIONS:
        python = PYTHONS[version]
        dest = snapshot_file(version)
        cmd = [
            python, "-m", "pip_audit", "--local", "--strict",
            "--format", "json", "--desc", "off", "--aliases", "off",
            "--progress-spinner", "off",
            "--cache-dir", "/opt/arvor/audit-cache",
            "--output", str(dest),
        ]
        subprocess.run(cmd, check=True, timeout=300)
        data = dest.read_bytes()
        audit = audited_packages(json.loads(data))
        inventory = installed_packages(python)
        if inventory != audit:
            missing = sorted(set(inventory) - set(audit))
            extra = sorted(set(audit) - set(inventory))
            wrong = sorted(k for k in inventory.keys() & audit.keys()
                           if inventory[k] != audit[k])
            raise ValueError(f"Audit omitted or mismatched packages: "
                             f"missing={missing}, extra={extra}, versions={wrong}")
        manifest["versions"][version] = {
            "snapshot_sha256": hashlib.sha256(data).hexdigest(),
            "packages": inventory,
        }
    manifest["created_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    print("BUILD AUDIT OK: all installed packages audited on both Python versions")


def verify():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict)
            or manifest.get("schema") != "arvor-ci-audit-v1"
            or manifest.get("service") != "pypi"
            or set(manifest.get("versions", {})) != set(VERSIONS)):
        raise ValueError("Untrusted or incomplete audit manifest")
    created = datetime.fromisoformat(manifest["created_at"])
    if created.tzinfo is None:
        raise ValueError("Naive audit timestamp")
    age = datetime.now(timezone.utc) - created
    if age < -timedelta(minutes=2) or age > MAX_AGE:
        raise ValueError("Vulnerability audit expired: rebuild trusted image")
    for version in VERSIONS:
        record = manifest["versions"][version]
        inventory = installed_packages(PYTHONS[version])
        if inventory != record["packages"]:
            raise ValueError("Python installed package inventory changed: " + version)
        audit = read_snapshot(version, record["snapshot_sha256"])
        if audit != inventory:
            raise ValueError("Vulnerability snapshot does not cover installed packages: " + version)
    print("OFFLINE DEPENDENCY AUDIT OK: 3.12 and 3.14, complete PyPI snapshots; "
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
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        print("DEPENDENCY AUDIT BLOCKED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
