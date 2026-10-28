"""Read-only technical critic for a private Arvor MP4 export.

It verifies measurable file properties, never claims artistic or audiovisual
perception. No generated media, no remote I/O, no secrets or paths in output.
"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


def _safe_file(folder, name, maximum):
    file = folder / name
    if file.is_symlink() or not file.is_file() or file.stat().st_size > maximum:
        raise ValueError("media_missing_or_unsafe")
    return file


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def validate_subtitles(text, duration_ms=75000):
    """Validate SRT structure/timing only, never infer speech alignment."""
    if not isinstance(text, str) or not text.strip():
        return "subtitles_empty"
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    blocks = re.split(r"\n[ \t]*\n", text.strip())
    previous_end = 0
    timestamp = r"(\d{2}):([0-5]\d):([0-5]\d),(\d{3})"
    for number, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0] != str(number):
            return "subtitles_structure_invalid"
        match = re.fullmatch(timestamp + r" --> " + timestamp, lines[1])
        if not match:
            return "subtitles_timestamp_invalid"
        values = [int(value) for value in match.groups()]
        def milliseconds(parts):
            hours, minutes, seconds, millis = parts
            return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
        start, end = milliseconds(values[:4]), milliseconds(values[4:])
        if start >= end or end > duration_ms:
            return "subtitles_timing_invalid"
        if start < previous_end:
            return "subtitles_overlap"
        if not any(line.strip() for line in lines[2:]):
            return "subtitles_text_missing"
        previous_end = end
    return None


def inspect_export(directory):
    """Evaluate only a locally rendered Arvor export with receipt.json."""
    checks = []
    folder = Path(directory)
    if folder.is_symlink() or not folder.is_dir():
        return {"technical_passed": False, "findings": ["unsafe_export_directory"],
                "visual_review_required": True, "human_release_required": True}
    try:
        video = _safe_file(folder, "episode.mp4", 2 * 1024**3)
        receipt_file = _safe_file(folder, "receipt.json", 64000)
        subtitles = _safe_file(folder, "narration.srt", 262144)
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
            raise ValueError("receipt_invalid")
        if _hash(video) != receipt.get("video_sha256"):
            checks.append("video_sha256_mismatch")
        if receipt.get("duration_seconds") != 75:
            checks.append("receipt_duration_not_75")
        dimensions = (receipt.get("width"), receipt.get("height"))
        if dimensions not in {(720, 1280), (1080, 1920)}:
            checks.append("receipt_format_not_vertical")
        if receipt.get("audio") is not True:
            checks.append("voice_not_present_in_receipt")
        subtitle_error = validate_subtitles(subtitles.read_text(encoding="utf-8"))
        if subtitle_error:
            checks.append(subtitle_error)
        executable = shutil.which("ffprobe")
        if not executable:
            checks.append("ffprobe_missing")
        else:
            try:
                completed = subprocess.run(
                    [executable, "-v", "error", "-show_entries",
                     "format=duration:stream=codec_type,width,height,r_frame_rate",
                     "-of", "json", str(video)],
                    check=True, capture_output=True, timeout=20)
                if len(completed.stdout) > 64000:
                    raise ValueError("ffprobe_output_too_large")
                probe = json.loads(completed.stdout)
                duration = float(probe["format"]["duration"])
                if not 74.75 <= duration <= 75.25:
                    checks.append("video_duration_not_75")
                video_streams = [s for s in probe["streams"] if s.get("codec_type") == "video"]
                audio_streams = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
                if len(video_streams) != 1 or len(audio_streams) != 1:
                    checks.append("video_audio_streams_invalid")
                if len(video_streams) == 1:
                    stream = video_streams[0]
                    if ((stream.get("width"), stream.get("height")) != dimensions
                            or dimensions not in {(720, 1280), (1080, 1920)}):
                        checks.append("video_not_9_16")
                    if stream.get("r_frame_rate") != "24/1":
                        checks.append("video_framerate_not_24")
            except (subprocess.SubprocessError, OSError, ValueError, KeyError,
                    TypeError, OverflowError):
                checks.append("ffprobe_failed")
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError):
        checks.append("export_missing_invalid_or_unsafe")
    return {"technical_passed": not checks, "findings": checks,
            "visual_review_required": True, "human_release_required": True,
            "scope": "technical_mp4_checks_only"}
