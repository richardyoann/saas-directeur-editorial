"""Media contracts remain usable without HTTP, storage or application imports."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

from editorial import media_rules as rules

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


class MediaRuleTests(unittest.TestCase):
    def test_private_endpoint_allowlist(self):
        for endpoint in ("http://localhost:8082", "https://10.0.0.1", "http://172.31.0.1",
                         "http://192.168.1.2", "http://[::1]", "http://[fd00::1]"):
            with self.subTest(endpoint=endpoint):
                self.assertTrue(rules.private_image_url(endpoint))
        for endpoint in ("https://example.com", "http://8.8.8.8", "http://169.254.169.254",
                         "http://[fe80::1]", "http://0.0.0.0", "ftp://127.0.0.1",
                         "http://127.0.0.1/path", "http://127.0.0.1?x=y",
                         "http://127.0.0.1#fragment", "http://user@127.0.0.1", ""):
            with self.subTest(endpoint=endpoint):
                self.assertFalse(rules.private_image_url(endpoint))

    def test_png_dimensions_and_original_bytes(self):
        self.assertEqual(rules.validate_png(PNG), (1, 1))
        for width, height in ((1, 2048), (2048, 1), (2048, 2048)):
            data = PNG[:16] + struct.pack(">II", width, height) + PNG[24:]
            self.assertEqual(rules.validate_png(data), (width, height))
        self.assertEqual(len(PNG), 68)

    def test_png_rejects_invalid_type_header_dimensions_and_size(self):
        invalid = [None, bytearray(PNG), PNG[:44], b"x" * 68,
                   PNG[:12] + b"BAD!" + PNG[16:],
                   PNG[:8] + b"\x00\x00\x00\x0c" + PNG[12:],
                   PNG + b"x" * rules.MAX_PNG_BYTES]
        for width, height in ((0, 1), (1, 0), (2049, 1), (1, 2049)):
            invalid.append(PNG[:16] + struct.pack(">II", width, height) + PNG[24:])
        for data in invalid:
            with self.subTest(kind=type(data).__name__, size=len(data) if data is not None else None):
                with self.assertRaises(rules.ImageUnavailable) as failure:
                    rules.validate_png(data)
                self.assertEqual(failure.exception.code, "image_provider_invalid_or_unavailable")

    def test_prompt_and_provenance_are_stable(self):
        board = {"cast": [{"name": "Marin", "appearance": "Manteau bleu",
                           "personality": "Calme", "role": "Témoin"}],
                 "scenes": [{"characters": ["Marin"], "colors": ["bleu"],
                             "title": "Le port", "visual_description": "Un quai",
                             "landscape": "Bretagne", "shot": "large",
                             "emotion": "calme", "image_prompt": "Une lanterne"}]}
        run = {"storyboard": board}
        expected = ("Illustration cinématique cohérente pour une légende bretonne. "
                    "Aucune inscription ni texte dans l'image. Scène 1 : Le port. "
                    "Sujet : Un quai. Personnages : Marin. "
                    "Repères visuels permanents : Marin : Manteau bleu. "
                    "Paysage : Bretagne. Palette : bleu. Cadrage : large. "
                    "Ambiance : calme. Description artistique : Une lanterne.")
        self.assertEqual(rules.image_prompt(run, 1), expected)
        refs = [{**board["cast"][0], "first_scene": 1, "scenes": [1]}]
        seed = rules.image_seed("scene-1")
        self.assertEqual(rules.image_provenance(run, 1, expected, seed=seed), {
            "contract_version": "private-image-v2", "provider": "sd.cpp-compatible",
            "parameters": {"n": 1, "size": "512x512", "output_format": "png"},
            "sample_parameters": rules.IMAGE_SAMPLE_PARAMETERS,
            "model": None, "seed": seed,
            "model_seed_reason": "seed_and_sampling_controlled_by_request",
            "prompt_sha256": hashlib.sha256(expected.encode()).hexdigest(),
            "character_reference_sha256": hashlib.sha256(json.dumps(
                refs, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
            "character_references": refs, "scene_number": 1,
            "gpu_verified": False, "vram_peak_bytes": None})
        with self.assertRaises(ValueError):
            rules.image_prompt(run, 2)
        board["scenes"][0]["image_prompt"] = "x" * 14000
        with self.assertRaises(rules.ImagePromptTooLong):
            rules.image_prompt(run, 1)

    def test_character_deduplication_keeps_order_and_scene_numbers(self):
        self.assertEqual(rules.characters({"scenes": [
            {"characters": ["Marin", "marin"]}, {"characters": ["MARIN", "Roi"]}]}), [
                {"name": "Marin", "appearance": None, "personality": None, "role": None,
                 "first_scene": 1, "scenes": [1, 2]},
                {"name": "Roi", "appearance": None, "personality": None, "role": None,
                 "first_scene": 2, "scenes": [2]}])

    def test_rules_import_without_loading_adapters(self):
        result = subprocess.run([sys.executable, "-c",
            "import sys; import editorial.media_rules; "
            "assert not any(n in sys.modules for n in "
            "('editorial.visuals','editorial.media_storage','httpx','boto3','fastapi','psycopg'))"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_storage_does_not_import_visuals_even_lazily(self):
        tree = ast.parse(Path("editorial/media_storage.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "editorial.visuals")
            elif isinstance(node, ast.Import):
                self.assertNotIn("editorial.visuals", [a.name for a in node.names])
