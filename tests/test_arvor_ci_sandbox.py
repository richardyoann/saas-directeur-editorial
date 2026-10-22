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

    def test_refuses_mutable_image_and_invalid_target(self):
        with self.assertRaises(ValueError):
            build_docker_command('arvor/ci:latest', self.checkout, self.trusted, self.evidence, SHA, BASE, 215)
        with self.assertRaises(ValueError):
            build_docker_command(IMAGE, self.checkout, self.checkout, self.evidence, SHA, BASE, 215)
