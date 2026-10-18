"""Check synthetic acceptance input and failure contract without a 75s CI cost."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import smoke_video_75


class Video75SmokeTests(unittest.TestCase):
    def test_synthetic_png_is_a_real_png_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.png'
            smoke_video_75.synthetic_png(path)
            self.assertTrue(path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))

    def test_fails_closed_without_video_tools(self):
        with patch('scripts.smoke_video_75.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'ffmpeg_or_ffprobe_unavailable'):
                smoke_video_75.smoke()


if __name__ == '__main__':
    unittest.main()
