"""Verify secret scan remains immutable and never posts private findings."""
from pathlib import Path
import unittest


class SecretScanPolicyTests(unittest.TestCase):
    def test_pinned_gitleaks_and_minimal_token_permissions(self):
        repo = Path(__file__).resolve().parents[1]
        scan = (repo / ".github" / "workflows" / "secret-scan.yml").read_text()
        self.assertIn("contents: read", scan)
        self.assertNotIn("issues: write", scan)
        self.assertNotIn("pull-requests: write", scan)
        self.assertIn("gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e", scan)
        self.assertIn("fetch-depth: 0", scan)
        for name in ("GITLEAKS_ENABLE_COMMENTS", "GITLEAKS_ENABLE_UPLOAD_ARTIFACT",
                     "GITLEAKS_ENABLE_SUMMARY"):
            self.assertIn(name + ": 'false'", scan)

    def test_critical_secret_scan_is_monitored(self):
        repo = Path(__file__).resolve().parents[1]
        watch = (repo / "scripts" / "ci_annotation_watch.py").read_text()
        triggers = (repo / ".github" / "workflows" / "ci-annotations.yml").read_text()
        self.assertIn('"Secret exposure scan"', watch)
        self.assertIn("      - Secret exposure scan", triggers)


if __name__ == "__main__":
    unittest.main()
