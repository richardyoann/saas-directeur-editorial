import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

spec = importlib.util.spec_from_file_location("archive_episode", Path(__file__).resolve().parents[1] / "scripts/archive_episode.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
restore_spec = importlib.util.spec_from_file_location("restore_episode", Path(__file__).resolve().parents[1] / "scripts/restore_episode_media.py")
restore_module = importlib.util.module_from_spec(restore_spec)
restore_spec.loader.exec_module(restore_module)


class ArchiveEpisodeTests(unittest.TestCase):
    def test_files_are_recorded_and_a_second_attempt_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("episode.mp4", "voice.wav", "scene-1.png"):
                (root / name).write_bytes(b"synthetic")
            store = MagicMock()
            store.get.return_value = {"status": "approved"}
            with patch.dict(os.environ, {"EDITORIAL_TENANT_ID": str(uuid4()), "EDITORIAL_ACTOR_ID": str(uuid4()), "PO_DATABASE_URL": "disposable"}), patch.object(module, "PostgresStore", return_value=store), patch.object(module, "put_file", return_value={"backend": "minio"}) as upload:
                self.assertEqual(module.archive(root, uuid4()), 3)
                self.assertEqual(store.record_media.call_count, 3)
                with self.assertRaises(FileExistsError):
                    module.archive(root, uuid4())
                self.assertEqual(upload.call_count, 3)
            events = [json.loads(line) for line in (root / "minio-archive.jsonl").read_text().splitlines()]
            self.assertEqual([event["state"] for event in events], ["started", "stored", "recorded"] * 3)
            self.assertTrue((root / "voice.wav").exists())
            first = next(event for event in events if event["state"] == "started")
            from uuid import UUID
            with patch.object(restore_module, "get_file", side_effect=lambda reference, target, *args: target.write_bytes(b"restored")) as download:
                self.assertEqual(restore_module.restore(root / "minio-archive.jsonl", root / "restored", UUID(first["tenant"]), UUID(first["run_id"])), 3)
                self.assertEqual(download.call_count, 3)
                self.assertTrue((root / "restored/episode.mp4").exists())
            with self.assertRaises(ValueError):
                restore_module.restore(root / "minio-archive.jsonl", root / "wrong-tenant", uuid4(), UUID(first["run_id"]))

    def test_db_failure_keeps_object_reference_and_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "episode.mp4").write_bytes(b"synthetic")
            store = MagicMock()
            store.get.return_value = {"status": "approved"}
            store.record_media.side_effect = RuntimeError("uncertain ack")
            with patch.dict(os.environ, {"EDITORIAL_TENANT_ID": str(uuid4()), "EDITORIAL_ACTOR_ID": str(uuid4()), "PO_DATABASE_URL": "disposable"}), patch.object(module, "PostgresStore", return_value=store), patch.object(module, "put_file", return_value={"backend": "minio"}):
                with self.assertRaises(RuntimeError):
                    module.archive(root, uuid4())
            self.assertIn('"state": "stored"', (root / "minio-archive.jsonl").read_text())
            self.assertTrue((root / "episode.mp4").exists())
