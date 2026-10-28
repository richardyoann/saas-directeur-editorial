import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from infrastructure.media import s3 as storage


class MediaStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ids = uuid4(), uuid4(), uuid4()
        self.payload = b"private-media"
        self.source = self.root / "source.wav"
        self.source.write_bytes(self.payload)
        self.api = MagicMock()
        self.api.put_object.return_value = {"VersionId": "version-1"}
        self.api.head_object.return_value = {"ContentLength": len(self.payload), "Metadata": {"sha256": hashlib.sha256(self.payload).hexdigest()}}
        for name, value in (("client", self.api), ("bucket", "private-media")):
            mock = patch.object(storage, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_upload_is_conditional_and_records_integrity_and_version(self):
        reference = storage.put_file(self.source, *self.ids, "voice")
        params = self.api.put_object.call_args.kwargs
        self.assertEqual(params["IfNoneMatch"], "*")
        self.assertEqual(params["Key"], storage.object_key(*self.ids, "voice"))
        self.assertEqual(reference["version_id"], "version-1")
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.api.head_object.assert_called_once_with(Bucket="private-media", Key=reference["key"], VersionId="version-1")

    def test_attempt_keys_are_distinct_and_validated(self):
        first = storage.object_key(*self.ids, "voice")
        second = storage.object_key(*self.ids, "voice", 2)
        self.assertNotEqual(first, second)
        self.assertTrue(second.endswith("-a2.wav"))
        reference = {"backend": "minio", "bucket": "private-media", "key": second,
                     "kind": "voice", "size": len(self.payload),
                     "sha256": hashlib.sha256(self.payload).hexdigest(), "attempt": 3}
        with self.assertRaisesRegex(storage.MediaStorageError, "media_reference_invalid"):
            storage.get_file(reference, self.root / "copy.wav", *self.ids, "voice")
        for invalid in (0, 1001, "2", True):
            with self.assertRaisesRegex(storage.MediaStorageError, "media_attempt_invalid"):
                storage.object_key(*self.ids, "voice", invalid)

    def test_timeout_reuses_only_an_identical_object(self):
        self.api.put_object.side_effect = TimeoutError()
        reference = storage.put_file(self.source, *self.ids, "voice")
        self.assertEqual(reference["sha256"],
                         hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(self.api.put_object.call_count, 1)
        self.api.delete_object.assert_not_called()

    def test_timeout_without_a_verified_object_is_uncertain_and_never_deletes(self):
        self.api.put_object.side_effect = TimeoutError()
        self.api.head_object.side_effect = Exception("not found")
        with self.assertRaisesRegex(storage.MediaStorageError, "media_upload_uncertain"):
            storage.put_file(self.source, *self.ids, "voice")
        self.assertEqual(self.api.put_object.call_count, 1)
        self.api.delete_object.assert_not_called()

    def test_timeout_with_different_bytes_is_refused_without_deleting(self):
        self.api.put_object.side_effect = TimeoutError()
        self.api.head_object.return_value = {"ContentLength": 3,
                                             "Metadata": {"sha256": "f" * 64}}
        with self.assertRaisesRegex(storage.MediaStorageError, "media_upload_conflict"):
            storage.put_file(self.source, *self.ids, "voice")
        self.api.delete_object.assert_not_called()

    def test_s3_client_disables_retries_and_requires_private_endpoint(self):
        with patch.dict("os.environ", {"MEDIA_S3_ENDPOINT": "https://public.example", "MEDIA_S3_ACCESS_KEY": "test", "MEDIA_S3_SECRET_KEY": "test"}):
            # The real factory, outside the fixture's patched client.
            import importlib.util
            spec = importlib.util.spec_from_file_location("storage_config_test", Path(storage.__file__))
            fresh = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fresh)
            with self.assertRaises(fresh.MediaStorageError):
                fresh.client()

    def test_uncertain_image_upload_keeps_local_recovery_png(self):
        from editorial.visuals import save_png, ImageUnavailable
        from test_visuals import PNG
        self.api.put_object.side_effect = TimeoutError()
        with patch.dict("os.environ", {"EDITORIAL_MEDIA_BACKEND": "minio", "EDITORIAL_MEDIA_ROOT": str(self.root)}):
            with self.assertRaisesRegex(ImageUnavailable, "image_storage_result_uncertain"):
                save_png(*self.ids, PNG)
        self.assertEqual(list(self.root.rglob("*.png"))[0].read_bytes(), PNG)
        self.assertEqual(list(self.root.rglob("*.png"))[0].stat().st_mode & 0o777, 0o600)

    def test_successful_image_upload_keeps_recovery_until_database_ack(self):
        from editorial.visuals import save_png
        from test_visuals import PNG
        reference = {"backend": "minio", "key": "private"}
        with patch.dict("os.environ", {
                "EDITORIAL_MEDIA_BACKEND": "minio",
                "EDITORIAL_MEDIA_ROOT": str(self.root)}), \
                patch.object(storage, "put_file", return_value=reference):
            saved = save_png(*self.ids, PNG)
        self.assertEqual(saved[0], reference)
        self.assertTrue(saved[1].is_file())
        saved[1].unlink()
        self.assertFalse(saved[1].exists())

    def test_download_checks_hash_and_rejects_cross_tenant_reference(self):
        reference = storage.put_file(self.source, *self.ids, "voice")
        self.api.get_object.return_value = {"ContentLength": len(self.payload), "Body": io.BytesIO(self.payload)}
        destination = self.root / "download.wav"
        storage.get_file(reference, destination, *self.ids, "voice")
        self.assertEqual(destination.read_bytes(), self.payload)
        with self.assertRaises(storage.MediaStorageError):
            storage.get_file(reference, self.root / "other.wav", uuid4(), *self.ids[1:], "voice")
        self.assertEqual(self.api.get_object.call_count, 1)

    def test_download_close_and_cleanup_errors_are_redacted(self):
        reference = storage.put_file(self.source, *self.ids, "voice")
        body = MagicMock()
        body.read.side_effect = [self.payload, b""]
        body.close.side_effect = RuntimeError("SECRET_SENTINEL")
        self.api.get_object.return_value = {"ContentLength": len(self.payload), "Body": body}
        target = self.root / "close-failed.wav"
        with self.assertRaises(storage.MediaStorageError) as caught:
            storage.get_file(reference, target, *self.ids, "voice")
        self.assertEqual(str(caught.exception), "media_download_failed")
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertFalse(target.exists())
        self.api.get_object.side_effect = RuntimeError("SECRET_SENTINEL")
        with patch.object(Path, "unlink", side_effect=OSError("SECRET_SENTINEL")):
            with self.assertRaises(storage.MediaStorageError) as caught:
                storage.get_file(reference, self.root / "cleanup-failed.wav", *self.ids, "voice")
        self.assertEqual(str(caught.exception), "media_download_failed")
        self.assertTrue(caught.exception.__suppress_context__)

    def test_corrupt_download_is_removed_without_touching_existing_file(self):
        reference = storage.put_file(self.source, *self.ids, "voice")
        self.api.get_object.return_value = {"ContentLength": len(self.payload), "Body": io.BytesIO(b"x" * len(self.payload))}
        destination = self.root / "download.wav"
        with self.assertRaises(storage.MediaStorageError):
            storage.get_file(reference, destination, *self.ids, "voice")
        self.assertFalse(destination.exists())
        destination.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            storage.get_file(reference, destination, *self.ids, "voice")
        self.assertEqual(destination.read_bytes(), b"existing")


class ConcurrentImageFileTests(unittest.TestCase):
    def test_exclusive_writers_do_not_overwrite_each_other(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from editorial.visuals import ImageUnavailable, save_png
        from test_visuals import PNG
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {
            'EDITORIAL_MEDIA_ROOT': directory, 'EDITORIAL_MEDIA_BACKEND': 'filesystem'}):
            ids = uuid4(), uuid4(), uuid4()
            barrier = Barrier(2)
            def write():
                barrier.wait(timeout=5)
                try:
                    return save_png(*ids, PNG)
                except ImageUnavailable:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: write(), range(2)))
            paths = [p for p in results if p is not None]
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].read_bytes(), PNG)
            self.assertEqual(paths[0].stat().st_mode & 0o777, 0o600)
