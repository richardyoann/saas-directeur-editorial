"""Private storage adapter: exclusivity, integrity, tenant scoping and images."""
import hashlib
import os
import stat
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from infrastructure.media import filesystem, production_media


def png_bytes():
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * ((8 * 4 + 1) * 8)))
            + chunk(b"IEND", b""))


class ProductionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "EDITORIAL_MEDIA_ROOT": str(self.root),
            "EDITORIAL_MEDIA_BACKEND": "filesystem",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tenant, self.run_id = uuid4(), uuid4()

    def source(self, name="source.wav", data=b"RIFF" + b"\x00" * 8):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_save_is_exclusive_private_and_returns_a_scoped_reference(self):
        asset_id = uuid4()
        reference = production_media.save(self.source(), self.tenant, self.run_id,
                                          asset_id, "voice")
        destination = (self.root / str(self.tenant) / str(self.run_id) / "production"
                       / f"{asset_id}.wav")
        self.assertEqual(reference["key"], str(destination))
        self.assertEqual(reference["sha256"],
                         hashlib.sha256(b"RIFF" + b"\x00" * 8).hexdigest())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_save_reuses_an_identical_retry_and_refuses_other_bytes(self):
        asset_id = uuid4()
        reference = production_media.save(self.source(), self.tenant, self.run_id,
                                          asset_id, "voice")
        replay = production_media.save(self.source("retry.wav"), self.tenant,
                                       self.run_id, asset_id, "voice")
        self.assertEqual(replay, reference)
        changed = self.source("changed.wav", b"RIFF" + b"\x01" * 8)
        with self.assertRaises(production_media.ProductionStorageError) as caught:
            production_media.save(changed, self.tenant, self.run_id, asset_id, "voice")
        self.assertEqual(str(caught.exception), "production_storage_conflict")
        destination = Path(reference["key"])
        self.assertEqual(destination.read_bytes(), b"RIFF" + b"\x00" * 8)
        self.assertEqual(list(Path(reference["key"]).parent.glob(".production-*")), [])

    def test_save_rejects_wrong_kind_empty_and_symlinked_inputs(self):
        for path, kind in ((self.source("a.txt"), "voice"),
                           (self.source("empty.wav", b""), "voice"),
                           (self.source("big.srt", b"x" * (1024 * 1024 + 1)), "subtitles")):
            with self.subTest(path=path):
                with self.assertRaises(production_media.ProductionStorageError):
                    production_media.save(path, self.tenant, self.run_id, uuid4(), kind)
        target = self.source("target.wav")
        link = self.root / "link.wav"
        link.symlink_to(target)
        with self.assertRaises(production_media.ProductionStorageError):
            production_media.save(link, self.tenant, self.run_id, uuid4(), "voice")

    def test_save_requires_an_absolute_private_root(self):
        with patch.dict(os.environ, {"EDITORIAL_MEDIA_ROOT": "relative"}, clear=False):
            with self.assertRaises(production_media.ProductionStorageError):
                production_media.save(self.source(), self.tenant, self.run_id,
                                      uuid4(), "voice")
        missing = self.root / "absent"
        with patch.dict(os.environ, {"EDITORIAL_MEDIA_ROOT": str(missing)}, clear=False):
            with self.assertRaises(production_media.ProductionStorageError):
                production_media.save(self.source(), self.tenant, self.run_id,
                                      uuid4(), "voice")

    def test_load_roundtrip_and_integrity_checks(self):
        asset_id = uuid4()
        reference = production_media.save(self.source(), self.tenant, self.run_id,
                                          asset_id, "voice")
        destination = self.root / "copy.wav"
        production_media.load(reference, destination, self.tenant, self.run_id,
                              asset_id, "voice")
        self.assertEqual(destination.read_bytes(), b"RIFF" + b"\x00" * 8)
        destination.unlink()

        tampered = dict(reference, sha256="0" * 64)
        with self.assertRaises(production_media.ProductionStorageError):
            production_media.load(tampered, destination, self.tenant, self.run_id,
                                  asset_id, "voice")
        self.assertFalse(destination.exists())

        for wrong in (dict(reference, size=reference["size"] + 1),
                      dict(reference, kind="video"),
                      dict(reference, backend="minio"),
                      dict(reference, key=str(self.root / "elsewhere.wav"))):
            with self.subTest(wrong=wrong):
                with self.assertRaises(production_media.ProductionStorageError):
                    production_media.load(wrong, destination, self.tenant, self.run_id,
                                          asset_id, "voice")

    def test_load_is_tenant_scoped(self):
        asset_id = uuid4()
        reference = production_media.save(self.source(), self.tenant, self.run_id,
                                          asset_id, "voice")
        with self.assertRaises(production_media.ProductionStorageError):
            production_media.load(reference, self.root / "copy.wav", uuid4(), self.run_id,
                                  asset_id, "voice")
        with self.assertRaises(production_media.ProductionStorageError):
            production_media.load(reference, self.root / "copy.wav", self.tenant,
                                  uuid4(), asset_id, "voice")

    def test_load_refuses_a_symlinked_destination_component(self):
        asset_id = uuid4()
        reference = production_media.save(self.source(), self.tenant, self.run_id,
                                          asset_id, "voice")
        real = self.root / "real"
        real.mkdir()
        (self.root / "escape").symlink_to(real, target_is_directory=True)
        with self.assertRaises(production_media.ProductionStorageError):
            production_media.load(reference, self.root / "escape" / "copy.wav",
                                  self.tenant, self.run_id, asset_id, "voice")

    def test_image_filesystem_reference_uses_the_scene_id(self):
        scene_id = uuid4()
        location = filesystem.media_location(self.tenant, self.run_id, scene_id)
        filesystem.write_png(location, png_bytes())
        destination = self.root / "scene.png"
        production_media.load(str(location), destination, self.tenant, self.run_id,
                              scene_id, "image")
        self.assertEqual(destination.read_bytes(), png_bytes())
        destination.unlink()

        with self.assertRaises(production_media.ProductionStorageError):
            production_media.load(str(location), destination, self.tenant, self.run_id,
                                  uuid4(), "image")
        with self.assertRaises(production_media.ProductionStorageError):
            production_media.load(str(location), destination, uuid4(), self.run_id,
                                  scene_id, "image")

    def test_minio_image_reference_is_rejected_on_the_filesystem_backend(self):
        reference = {"backend": "minio", "bucket": "media", "kind": "image",
                     "key": "k", "sha256": "a" * 64, "size": 10}
        with self.assertRaises(production_media.ProductionStorageError):
            production_media.load(reference, self.root / "scene.png", self.tenant,
                                  self.run_id, uuid4(), "image")

    def test_open_reference_materialises_a_temporary_copy(self):
        asset_id = uuid4()
        reference = production_media.save(self.source(), self.tenant, self.run_id,
                                          asset_id, "voice")
        path, directory = production_media.open_reference(
            reference, self.tenant, self.run_id, asset_id, "voice")
        self.addCleanup(directory.cleanup)
        self.assertEqual(path.read_bytes(), b"RIFF" + b"\x00" * 8)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode) & 0o077, 0)

    def test_unknown_backend_is_rejected(self):
        with patch.dict(os.environ, {"EDITORIAL_MEDIA_BACKEND": "ftp"}, clear=False):
            with self.assertRaises(production_media.ProductionStorageError):
                production_media.backend()


if __name__ == "__main__":
    unittest.main()
