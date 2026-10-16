import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from editorial import media_storage as storage


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

    def test_timeout_is_not_replayed_and_never_deletes_objects(self):
        self.api.put_object.side_effect = TimeoutError()
        with self.assertRaisesRegex(storage.MediaStorageError, "media_upload_uncertain"):
            storage.put_file(self.source, *self.ids, "voice")
        self.assertEqual(self.api.put_object.call_count, 1)
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
        with patch.dict("os.environ", {"MEDIA_S3_ENDPOINT": "http://127.0.0.1:9000", "MEDIA_S3_ACCESS_KEY": "test", "MEDIA_S3_SECRET_KEY": "test"}):
            api = fresh.client()
            self.assertEqual(api.meta.config.retries["total_max_attempts"], 1)
            self.assertIn("IfNoneMatch", api.meta.service_model.operation_model("PutObject").input_shape.members)

    def test_uncertain_image_upload_keeps_local_recovery_png(self):
        from editorial.visuals import save_png, ImageUnavailable
        from test_visuals import PNG
        self.api.put_object.side_effect = TimeoutError()
        with patch.dict("os.environ", {"EDITORIAL_MEDIA_BACKEND": "minio", "EDITORIAL_MEDIA_ROOT": str(self.root)}):
            with self.assertRaisesRegex(ImageUnavailable, "image_storage_result_uncertain"):
                save_png(*self.ids, PNG)
        self.assertEqual(list(self.root.rglob("*.png"))[0].read_bytes(), PNG)

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
