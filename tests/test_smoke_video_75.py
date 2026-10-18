"""Check synthetic acceptance input and failure contract without a 75s CI cost."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from scripts import smoke_video_75


class Video75SmokeTests(unittest.TestCase):
    def test_nonfinite_duration_is_not_a_success(self):
        def fake_render(manifest, export):
            export.mkdir()
            (export / 'narration.srt').write_text('00:00:00,000 --> 00:01:15,000')
            return {'duration_seconds': 75}
        with patch.object(smoke_video_75.shutil, 'which', return_value='/test/tool'), \
             patch.object(smoke_video_75, 'render', side_effect=fake_render), \
             patch.object(smoke_video_75.subprocess, 'check_output', return_value=json.dumps({
                 'format': {'duration': 'NaN'},
                 'streams': [{'codec_type': 'video', 'width': 720, 'height': 1280}]
             }).encode()):
            with self.assertRaisesRegex(RuntimeError, 'video_duration_or_stream_invalid'):
                smoke_video_75.smoke()

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
