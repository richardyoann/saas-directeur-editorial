"""Offline 75-second MP4 acceptance smoke on synthetic assets only.

Never invokes a model, reads private media, persists production data or publishes.
"""
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib

from scripts.render_episode import render

DURATION = 75


def synthetic_png(path):
    """Write a minimal opaque 32x32 RGB PNG without extra dependencies."""
    def chunk(kind, payload):
        return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload) & 0xffffffff)
    pixels = b''.join(b'\x00' + b'\x20\x40\x80' * 32 for _ in range(32))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 32, 32, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def smoke():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('ffmpeg_or_ffprobe_unavailable')
    with tempfile.TemporaryDirectory(prefix='arvor-video-smoke-') as tmp:
        root = Path(tmp)
        synthetic_png(root / 'synthetic.png')
        manifest = root / 'source.json'
        manifest.write_text(json.dumps({'schema_version': 1, 'approved': True,
                                        'scenes': [{'image': 'synthetic.png',
                                                    'duration_seconds': DURATION,
                                                    'narration': 'Texte synthétique de recette.'}]}), encoding='utf-8')
        export = root / 'result'
        receipt = render(manifest, export)
        if receipt.get('duration_seconds') != DURATION:
            raise RuntimeError('incorrect_manifest_duration')
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_format', '-show_streams',
            '-of', 'json', str(export / 'episode.mp4')], timeout=15))
        actual = float(probe['format']['duration'])
        videos = [stream for stream in probe['streams'] if stream.get('codec_type') == 'video']
        if abs(actual - DURATION) > 0.25 or len(videos) != 1:
            raise RuntimeError('video_duration_or_stream_invalid')
        video = videos[0]
        if (video.get('width'), video.get('height')) != (720, 1280):
            raise RuntimeError('video_resolution_invalid')
        if '00:01:15,000' not in (export / 'narration.srt').read_text(encoding='utf-8'):
            raise RuntimeError('subtitle_duration_invalid')
    return {'verified': True, 'synthetic': True, 'video_duration_seconds': DURATION,
            'resolution': '720x1280', 'ffprobe': 'passed', 'data_mutation': False}


if __name__ == '__main__':
    try:
        print(json.dumps(smoke(), sort_keys=True))
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError):
        print(json.dumps({'verified': False, 'reason': 'offline_video_smoke_failed'}))
        raise SystemExit(1)
