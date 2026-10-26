"""Host trust manifest tests; generated keys remain confined to temp dirs."""
import json
import os
from pathlib import Path
import pwd
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import arvor_ci_host_trust as trustmod


class HostTrustTests(unittest.TestCase):
    def test_default_trust_anchor_ignores_home_environment_override(self):
        expected = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".config/arvor-local-ci/trust.json"
        with patch.dict(os.environ, {"HOME": "/tmp/arvor-untrusted-home"}):
            self.assertEqual(trustmod.DEFAULT_TRUST_PATH, expected)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = Ed25519PrivateKey.generate()
        self.private_pem = self.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        self.public_pem = self.private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        der = self.private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        import hashlib
        self.manifest = {
            "schema": "arvor-host-trust-v1",
            "repo": trustmod.REPO,
            "controller_path": str(self.root / "controller"),
            "controller_sha": "a" * 40,
            "trusted_policy_path": str(self.root / "trusted-policy"),
            "policy_sha256": "b" * 64,
            "image_id": "sha256:" + "c" * 64,
            "key_id": "arvor-local-v1",
            "private_key_path": str(self.root / "key.pem"),
            "public_key_path": str(self.root / "key.pub"),
            "public_key_sha256": hashlib.sha256(der).hexdigest(),
            "sent_dir": str(self.root / "sent"),
        }
        self.path = self.root / "trust.json"
        self._write()

    def _write(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.path.chmod(0o600)

    def test_loads_strict_host_pins_and_verifies_keypair(self):
        actual = trustmod.load_host_trust(self.path)
        self.assertEqual(actual["controller_sha"], "a" * 40)
        trustmod.verify_host_key(actual, self.public_pem)
        trustmod.verify_private_key(actual, self.private_pem)

    def test_rejects_unpinned_fingerprint(self):
        self.manifest["public_key_sha256"] = "0" * 64
        self._write()
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            trustmod.verify_host_key(trustmod.load_host_trust(self.path), self.public_pem)

    def test_rejects_wrong_key_id_and_unknown_fields(self):
        self.manifest["key_id"] = "bad/key"
        self._write()
        with self.assertRaisesRegex(ValueError, "Malformed"):
            trustmod.load_host_trust(self.path)
        self.manifest["key_id"] = "arvor-local-v1"
        self.manifest["operator_override"] = True
        self._write()
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            trustmod.load_host_trust(self.path)

    def test_rejects_loose_or_linked_manifest(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "0600"):
            trustmod.load_host_trust(self.path)
        link = self.root / "trust-link.json"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "symlink"):
            trustmod.load_host_trust(link)

    def test_rejects_invalid_policy_identity(self):
        self.manifest["policy_sha256"] = "not-a-digest"
        self._write()
        with self.assertRaisesRegex(ValueError, "Malformed"):
            trustmod.load_host_trust(self.path)

    def test_rejects_signer_outside_pinned_controller(self):
        actual = trustmod.load_host_trust(self.path)
        candidate_signer = self.root / "candidate" / "scripts" / "arvor_ci_attestation.py"
        candidate_signer.parent.mkdir(parents=True)
        candidate_signer.write_text("# candidate signer", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Signer must execute from pinned host controller"):
            trustmod.verify_host_signer(actual, candidate_signer)


if __name__ == "__main__":
    unittest.main()
