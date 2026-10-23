"""Host-side sandbox command safety unit tests. No Docker daemon required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.arvor_ci_sandbox import build_docker_command

SHA = 'a' * 40
BASE = 'b' * 40
IMAGE = 'sha256:' + 'c' * 64


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.checkout = self.root / 'checkout'
        self.trusted = self.root / 'trusted'
        self.evidence = self.root / 'evidence'
        for p in (self.checkout, self.trusted, self.evidence):
            p.mkdir()
        (self.checkout / '.git').mkdir()

    @patch('scripts.arvor_ci_sandbox.subprocess.run')
    def test_secure_docker_run(self, run):
        run.side_effect = [type('P', (), {'stdout': SHA + '\n'})(), type('P', (), {'stdout': ''})()]
        cmd = build_docker_command(IMAGE, self.checkout, self.trusted, self.evidence, SHA, BASE, 215)
        self.assertIn('--network=none', cmd)
        self.assertIn('--read-only', cmd)
        self.assertIn('--tmpfs=/tmp:rw,exec,nosuid,nodev,size=1073741824,uid=999,gid=999', cmd)
        self.assertIn('--shm-size=512m', cmd)
        self.assertNotIn('--ipc=host', cmd)
        self.assertIn('--cap-drop=ALL', cmd)
        self.assertIn('--security-opt=no-new-privileges', cmd)
        self.assertIn('--pull=never', cmd)
        self.assertNotIn('--privileged', cmd)
        self.assertFalse(any('docker.sock' in t for t in cmd))
        self.assertTrue(any('/workspace,readonly' in t for t in cmd))
        self.assertTrue(any('/trusted,readonly' in t for t in cmd))

    @patch('scripts.arvor_ci_sandbox.subprocess.run')
    def test_rejects_dirty_or_wrong_sha(self, run):
        run.return_value.stdout = 'f' * 40
        with self.assertRaises(ValueError):
            build_docker_command(IMAGE, self.checkout, self.trusted, self.evidence, SHA, BASE, 215)
        run.side_effect = [type('P', (), {'stdout': SHA})(), type('P', (), {'stdout': 'M file.py'})()]
        with self.assertRaises(ValueError):
            build_docker_command(IMAGE, self.checkout, self.trusted, self.evidence, SHA, BASE, 215)

    def test_audit_cache_access_for_non_root_sandbox(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "ci/local/Dockerfile").read_text(encoding="utf-8")
        entry = (root / "scripts/arvor_ci_entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("chown -R 999:999 /opt/arvor/audit-cache", dockerfile)
        self.assertIn("cp -R /opt/arvor/audit-cache/. /tmp/audit-cache/", entry)
        self.assertNotIn("\ncp -a /opt/arvor/audit-cache", entry)

    def test_playwright_headless_browser_is_installed_and_pinned(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "ci/local/Dockerfile").read_text(encoding="utf-8")
        controller = (root / "scripts/arvor_local_ci.py").read_text(encoding="utf-8")
        entry = (root / "scripts/arvor_ci_entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn("ENV PLAYWRIGHT_BROWSERS_PATH=/opt/arvor/playwright-browsers", dockerfile)
        self.assertIn("playwright install --with-deps --only-shell chromium", dockerfile)
        self.assertIn('"PLAYWRIGHT_BROWSERS_PATH", "PO_TEST_DATABASE_URL"', controller)
        self.assertIn("playwright.chromium.launch(headless=True", entry)
        self.assertIn("CI preflight: Playwright Chromium headless shell launched", entry)

    def test_offline_audit_covers_installed_environment_and_requirement_identity(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / 'ci/local/Dockerfile').read_text(encoding='utf-8')
        controller = (root / 'scripts/arvor_local_ci.py').read_text(encoding='utf-8')
        entry = (root / 'scripts/arvor_ci_entrypoint.sh').read_text(encoding='utf-8')
        self.assertIn('pip_audit --local --strict', dockerfile)
        self.assertIn('"pip_audit", "--local", "--strict"', controller)
        self.assertNotIn('"pip_audit", "-r", "requirements.txt"', controller)
        self.assertIn('Path("/workspace/requirements.txt")', entry)
        self.assertIn('metadata.version(name)', entry)
        self.assertIn("metadata.requires(name)", entry)
        self.assertIn("exact direct pins and extras match audited image", entry)
        self.assertIn('for python_bin in /opt/arvor/py312/bin/python /opt/arvor/py314/bin/python', entry)
        self.assertNotIn('/tmp/arvor-requirements.txt', entry)
        # Preflight Python is embedded in the trusted shell entrypoint.
        source = entry.split('for python_bin in /opt/arvor/py312/bin/python /opt/arvor/py314/bin/python', 1)[1]
        source = source.split("<<'PY'\\n", 1)[1].split('\\nPY\\ndone', 1)[0]
        compile(source, "arvor-ci-requirements-preflight", "exec")

    def test_refuses_mutable_image_and_invalid_target(self):
        with self.assertRaises(ValueError):
            build_docker_command('arvor/ci:latest', self.checkout, self.trusted, self.evidence, SHA, BASE, 215)
        with self.assertRaises(ValueError):
            build_docker_command(IMAGE, self.checkout, self.checkout, self.evidence, SHA, BASE, 215)
