"""Runtime secret externalization and Docker config security regression."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from editorial.runtime_secrets import secret, secret_from_sources
from scripts.ci_policy import audit_secret_configuration


class SecretTests(unittest.TestCase):
    def test_environment_keeps_private_compatibility(self):
        with patch.dict(os.environ, {"EDITORIAL_API_TOKEN": "x" * 40}, clear=True):
            self.assertEqual(secret("EDITORIAL_API_TOKEN"), "x" * 40)

    def test_files_and_systemd_credentials(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "EDITORIAL_API_TOKEN"
            path.write_text("a" * 40 + "\n")
            path.chmod(0o600)
            self.assertEqual(secret_from_sources("EDITORIAL_API_TOKEN", {
                "EDITORIAL_API_TOKEN_FILE": str(path)}), "a" * 40)
            self.assertEqual(secret_from_sources("EDITORIAL_API_TOKEN", {
                "CREDENTIALS_DIRECTORY": folder}), "a" * 40)

    def test_ambiguous_or_unsafe_source_fails_closed(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text("topsecret")
            path.chmod(0o600)
            name = "EDITORIAL_WEB_PASSWORD"
            self.assertEqual(secret_from_sources(name, {name: "direct", name+"_FILE": str(path)}), "")
            path.chmod(0o666)
            self.assertEqual(secret_from_sources(name, {name+"_FILE": str(path)}), "")
            path.chmod(0o600)
            link = Path(folder) / "link"
            link.symlink_to(path)
            self.assertEqual(secret_from_sources(name, {name+"_FILE": str(link)}), "")
            self.assertEqual(secret_from_sources(name, {name+"_FILE": "relative"}), "")
            path.write_text("foo\nbar")
            self.assertEqual(secret_from_sources(name, {name+"_FILE": str(path)}), "")
            path.write_bytes(b"a" * 17000)
            self.assertEqual(secret_from_sources(name, {name+"_FILE": str(path)}), "")

    def test_compose_secret_policy(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(audit_secret_configuration(root), [])
        with TemporaryDirectory() as folder:
            (Path(folder) / "compose.yml").write_text(
                "services:\n  postgres:\n    environment:\n      POSTGRES_PASSWORD: literal\n")
            self.assertTrue(audit_secret_configuration(Path(folder)))

    def test_private_delivery_uses_secret_file_without_leaking_to_test_process(self):
        from scripts.deploy_local import candidate_test_environment, deployment_secret
        with TemporaryDirectory() as folder:
            path = Path(folder) / "database"
            business = "postgresql://editor:private@127.0.0.1:5432/editorial"
            path.write_text(business)
            path.chmod(0o600)
            config = {"PO_DATABASE_URL_FILE": str(path)}
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(deployment_secret("PO_DATABASE_URL", config), business)
                candidate = candidate_test_environment(
                    "postgresql://po_test:ephemeral_ci_only@127.0.0.1:54323/po_test", config)
            self.assertEqual(candidate["PO_DATABASE_URL_FILE"], "")
            self.assertEqual(candidate["EDITORIAL_TENANT_ID_FILE"], "")
            self.assertEqual(candidate["EDITORIAL_ACTOR_ID_FILE"], "")
            self.assertNotEqual(candidate["PO_DATABASE_URL"], business)


if __name__ == "__main__":
    unittest.main()
