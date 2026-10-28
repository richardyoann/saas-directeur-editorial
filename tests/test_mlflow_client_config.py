"""Tests for the private MLflow client configuration loader and provisioning."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from infrastructure.observability.mlflow_env import (
    ClientEnvironmentError, load_client_environment)
from scripts import provision_mlflow_local as provision

SECRET = "SECRET_CLIENT_VALUE_NEVER_LOGGED"


def write_private_file(path, content, mode=0o600):
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)
    return path


class ClientEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        os.chmod(self.directory, 0o700)
        self.ca = write_private_file(self.directory / "minio-ca.crt", "CA")

    def tearDown(self):
        for child in sorted(self.directory.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        self.directory.rmdir()

    def env_file(self, **overrides):
        values = {
            "ARVOR_MLFLOW_ENABLED": "true",
            "MLFLOW_TRACKING_URI": "http://127.0.0.1:5000",
            "MLFLOW_TRACKING_USERNAME": "arvor-admin",
            "MLFLOW_TRACKING_PASSWORD": SECRET,
            "ARVOR_MLFLOW_SPOOL": str(self.directory / "spool/pending.jsonl"),
            "REQUESTS_CA_BUNDLE": str(self.ca),
            "AWS_CA_BUNDLE": str(self.ca),
        }
        values.update(overrides)
        text = "# comment\n" + "\n".join(f"{k}={v}" for k, v in values.items()) + "\n"
        return write_private_file(self.directory / "client.env", text)

    def test_loads_all_supported_keys_without_overriding(self):
        path = self.env_file()
        environ = {"MLFLOW_TRACKING_URI": "http://127.0.0.1:5001"}
        result = load_client_environment(path, environ)
        self.assertEqual(environ["MLFLOW_TRACKING_URI"], "http://127.0.0.1:5001")
        self.assertEqual(environ["REQUESTS_CA_BUNDLE"], str(self.ca))
        self.assertEqual(environ["AWS_CA_BUNDLE"], str(self.ca))
        self.assertEqual(environ["MLFLOW_TRACKING_PASSWORD"], SECRET)
        self.assertEqual(result, {"loaded": 6, "kept": 1})
        self.assertNotIn(SECRET, json.dumps(result))

    def test_unknown_keys_are_ignored(self):
        path = self.env_file()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("UNRELATED_DATABASE_URL=postgresql://secret\n")
        environ = {}
        load_client_environment(path, environ)
        self.assertNotIn("UNRELATED_DATABASE_URL", environ)

    def test_group_or_world_readable_file_is_refused(self):
        path = self.env_file()
        os.chmod(path, 0o644)
        with self.assertRaises(ClientEnvironmentError) as caught:
            load_client_environment(path, {})
        self.assertEqual(caught.exception.code, "env_file_permissions")

    def test_symbolic_link_is_refused(self):
        target = self.env_file()
        link = self.directory / "linked.env"
        link.symlink_to(target)
        with self.assertRaises(ClientEnvironmentError) as caught:
            load_client_environment(link, {})
        self.assertEqual(caught.exception.code, "env_file_symlink")

    def test_missing_or_relative_ca_is_refused(self):
        for value in (str(self.directory / "absent.crt"), "relative/ca.crt"):
            path = self.env_file(REQUESTS_CA_BUNDLE=value)
            with self.assertRaises(ClientEnvironmentError) as caught:
                load_client_environment(path, {})
            self.assertEqual(caught.exception.code, "ca_bundle_invalid")

    def test_the_app_process_loads_the_file_at_startup(self):
        path = self.env_file()
        environ = {"ARVOR_MLFLOW_ENV_FILE": str(path)}
        with patch.dict(os.environ, environ, clear=True):
            load_client_environment(os.environ["ARVOR_MLFLOW_ENV_FILE"])
            self.assertEqual(os.environ["MLFLOW_TRACKING_URI"], "http://127.0.0.1:5000")
            self.assertEqual(os.environ["REQUESTS_CA_BUNDLE"], str(self.ca))


class ProvisioningTests(unittest.TestCase):
    def test_client_file_contains_the_private_ca_and_stays_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config"
            state = root / "state"
            ca = write_private_file(root / "minio-ca.crt", "CA")
            provision.write_client_environment(config, state, SECRET, ca)
            path = config / "client.env"
            text = path.read_text(encoding="utf-8")
            self.assertIn(f"REQUESTS_CA_BUNDLE={ca.resolve()}", text)
            self.assertIn(f"AWS_CA_BUNDLE={ca.resolve()}", text)
            self.assertNotIn("verify=False", text)
            self.assertNotIn("MLFLOW_S3_IGNORE_TLS", text)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o700)

    def test_missing_ca_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises((RuntimeError, FileNotFoundError)):
                provision.write_client_environment(
                    root / "config", root / "state", SECRET, root / "absent.crt")


if __name__ == "__main__":
    unittest.main()
