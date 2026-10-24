"""Negative-path tests for an immutable, expiring, offline PyPI audit snapshot."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ci.local import audit_snapshot as audit


class AuditSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.pkg = {"example": "1.2.3"}
        self.report = {"dependencies": [
            {"name": "example", "version": "1.2.3", "vulns": []}
        ], "fixes": []}
        self.manifest = {
            "schema": "arvor-ci-audit-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "service": "pypi", "versions": {}
        }
        for version in audit.VERSIONS:
            raw = json.dumps(self.report).encode()
            (self.root / ("pip-audit-py" + version + ".json")).write_bytes(raw)
            self.manifest["versions"][version] = {
                "packages": dict(self.pkg),
                "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
            }
        self.save()
        p = patch.object(audit, "ROOT", self.root)
        q = patch.object(audit, "MANIFEST", self.root / "manifest.json")
        r = patch.object(audit, "installed_packages", return_value=self.pkg)
        for each in (p, q, r):
            each.start()
            self.addCleanup(each.stop)

    def save(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def test_fresh_audit_matching_all_installed_packages_passes(self):
        with patch.object(audit.subprocess, "run", side_effect=AssertionError("No network or installs during verification")):
            audit.verify()

    def test_expired_audit_fails_closed(self):
        self.manifest["created_at"] = (
            datetime.now(timezone.utc) - timedelta(days=2)
        ).isoformat()
        self.save()
        with self.assertRaisesRegex(ValueError, "expired"):
            audit.verify()

    def test_future_dated_audit_fails_closed(self):
        self.manifest["created_at"] = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        self.save()
        with self.assertRaisesRegex(ValueError, "expired"):
            audit.verify()

    def test_modified_snapshot_fails_hash_check(self):
        (self.root / "pip-audit-py312.json").write_text("not the real report")
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            audit.verify()

    def test_new_vulnerability_even_with_matching_digest_is_rejected(self):
        self.report["dependencies"][0]["vulns"] = [{"id": "GHSA-test"}]
        self.replace_snapshot("312")
        with self.assertRaisesRegex(ValueError, "Vulnerable"):
            audit.verify()

    def test_skipped_package_even_with_matching_digest_is_rejected(self):
        self.report["dependencies"][0]["skip_reason"] = "unavailable"
        self.replace_snapshot("312")
        with self.assertRaisesRegex(ValueError, "skipped"):
            audit.verify()

    def test_installed_packages_change_is_rejected(self):
        self.manifest["versions"]["312"]["packages"]["example"] = "1.2.4"
        self.save()
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            audit.verify()

    def test_snapshot_missing_package_is_rejected(self):
        self.report["dependencies"] = [
            {"name": "other", "version": "1.2.3", "vulns": []}
        ]
        self.replace_snapshot("312")
        with self.assertRaisesRegex(ValueError, "does not cover"):
            audit.verify()

    def test_missing_one_python_audit_fails(self):
        self.manifest["versions"].pop("314")
        self.save()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            audit.verify()

    def test_build_fails_if_pip_audit_reports_failure(self):
        with patch.object(audit.subprocess, "run",
                          side_effect=subprocess.CalledProcessError(1, "pip-audit")):
            with self.assertRaises(subprocess.CalledProcessError):
                audit.build()

    def replace_snapshot(self, version):
        raw = json.dumps(self.report).encode()
        (self.root / ("pip-audit-py" + version + ".json")).write_bytes(raw)
        self.manifest["versions"][version]["snapshot_sha256"] = (
            hashlib.sha256(raw).hexdigest()
        )
        self.save()


if __name__ == "__main__":
    unittest.main()
