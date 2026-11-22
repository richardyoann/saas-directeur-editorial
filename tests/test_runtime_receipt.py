"""Regression tests for untrusted delivery receipt metadata; no PC services."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "diagnose_runtime_receipt", Path(__file__).resolve().parents[1] / "scripts" / "diagnose_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
SHA = "a" * 40


class ReceiptTests(unittest.TestCase):
    def inspect(self, raw, current_sha=SHA):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / (current_sha + "-1")
            target.mkdir()
            (root / "current").symlink_to(target, target_is_directory=True)
            if raw is not None:
                (root / "last_delivery.json").write_bytes(raw)
            before = (root / "last_delivery.json").read_bytes() if raw is not None else None
            result = runtime.release_info(root, SHA)
            if raw is not None:
                self.assertEqual((root / "last_delivery.json").read_bytes(), before)
            return result

    def test_valid_receipt(self):
        result = self.inspect(json.dumps({"sha": SHA}).encode())
        self.assertTrue(result["expected_sha_matches"])
        self.assertTrue(result["release_receipt_consistent"])

    def test_mismatching_release(self):
        result = self.inspect(json.dumps({"sha": SHA}).encode(), "b" * 40)
        self.assertFalse(result["expected_sha_matches"])
        self.assertFalse(result["release_receipt_consistent"])

    def test_non_object_json(self):
        for raw in (b"[]", b"null", b"42", b"true", b'"text"'):
            with self.subTest(raw=raw):
                result = self.inspect(raw)
                self.assertIsNone(result["receipt_sha"])
                self.assertFalse(result["expected_sha_matches"])
                self.assertFalse(result["release_receipt_consistent"])

    def test_corrupt_receipts(self):
        for raw in (b"{", b"\xff", b"[" * 2000 + b"]" * 2000):
            with self.subTest(size=len(raw)):
                result = self.inspect(raw)
                self.assertIsNone(result["receipt_sha"])
                self.assertFalse(result["expected_sha_matches"])

    def test_invalid_sha(self):
        for value in (None, [], 123, "short", "A" * 40):
            with self.subTest(value=value):
                self.assertIsNone(self.inspect(json.dumps({"sha": value}).encode())["receipt_sha"])

    def test_missing_receipt(self):
        result = self.inspect(None)
        self.assertFalse(result["receipt_present"])
        self.assertFalse(result["expected_sha_matches"])


if __name__ == "__main__":
    unittest.main()
