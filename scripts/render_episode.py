"""Offline, private slideshow export. No model calls, DB writes or publication."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(root, name, suffix):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("asset_path_invalid")
    path = root / name
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("asset_symlink_forbidden")
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != suffix:
        raise ValueError("asset_path_invalid")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("asset_too_large")
    return path


def run(command):
    try:
        return subprocess.run(command, check=True, capture_output=True, timeout=300).stdout
    except (subprocess.SubprocessError, OSError):
        raise ValueError("media_command_failed") from None


def stamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def render(manifest, destination):
    manifest, destination = Path(manifest).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination_exists")
    if manifest.stat().st_size > 128000:
        raise ValueError("manifest_too_large")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("approved") is not True:
        raise ValueError("approved_manifest_required")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 6:
        raise ValueError("scene_count_invalid")
    assets, total = [], 0
    for scene in scenes:
        duration = scene.get("duration_seconds")
        narration = scene.get("narration")
        if type(duration) is not int or not 1 <= duration <= 180:
            raise ValueError("scene_duration_invalid")
        if not isinstance(narration, str) or not narration.strip() or len(narration) > 4000:
            raise ValueError("narration_invalid")
        assets.append(local_file(manifest.parent, scene.get("image"), ".png"))
        total += duration
    if total > 180:
        raise ValueError("episode_duration_invalid")
    voice = local_file(manifest.parent, data["voice"], ".wav") if data.get("voice") else None
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ValueError("ffmpeg_and_ffprobe_required")
    if voice:
        seconds = float(run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-f", "wav", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(voice)]))
        if not math.isfinite(seconds) or abs(seconds - total) > 0.25:
            raise ValueError("voice_duration_mismatch")
    # Exclusive directory creation also prevents concurrent exports from overwriting.
    destination.mkdir(mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix=".render-", dir=destination) as work:
            work = Path(work)
            subtitles, cursor = [], 0
            receipts = []
            for index, (scene, image) in enumerate(zip(scenes, assets), 1):
                copied = work / f"scene-{index}.png"
                shutil.copyfile(image, copied)
                receipts.append({"scene": index, "image_sha256": digest(copied), "duration_seconds": scene["duration_seconds"]})
                run([ffmpeg, "-nostdin", "-v", "error", "-n", "-threads", "1", "-protocol_whitelist", "file,pipe", "-f", "image2", "-c:v", "png", "-loop", "1", "-i", str(copied),
                     "-t", str(scene["duration_seconds"]), "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1",
                     "-r", "24", "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(work / f"clip-{index}.mp4")])
                text = " ".join(scene["narration"].split())
                subtitles.append(f"{index}\n{stamp(cursor)} --> {stamp(cursor + scene['duration_seconds'])}\n{text}\n")
                cursor += scene["duration_seconds"]
            (work / "clips.txt").write_text("".join(f"file 'clip-{i}.mp4'\n" for i in range(1, len(scenes) + 1)), encoding="utf-8")
            command = [ffmpeg, "-nostdin", "-v", "error", "-n", "-f", "concat", "-safe", "1", "-i", str(work / "clips.txt")]
            if voice:
                shutil.copyfile(voice, work / "voice.wav")
                command += ["-protocol_whitelist", "file,pipe", "-f", "wav", "-i", str(work / "voice.wav"), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-t", str(total)]
            command += ["-c:v", "copy", "-movflags", "+faststart", str(destination / "episode.mp4")]
            run(command)
            probe = json.loads(run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(destination / "episode.mp4")]))
            if abs(float(probe["format"]["duration"]) - total) > 0.25:
                raise ValueError("export_duration_mismatch")
            (destination / "narration.srt").write_text("\n".join(subtitles), encoding="utf-8")
            # A self-contained production folder preserves inputs for replay.
            for index in range(1, len(scenes) + 1):
                shutil.copyfile(work / f"scene-{index}.png", destination / f"scene-{index}.png")
                data["scenes"][index - 1]["image"] = f"scene-{index}.png"
            if voice:
                shutil.copyfile(work / "voice.wav", destination / "voice.wav")
                data["voice"] = "voice.wav"
            (destination / "production.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            receipt = {"schema_version": 1, "duration_seconds": total, "width": 720, "height": 1280,
                       "audio": bool(voice), "subtitles": "sidecar", "scenes": receipts,
                       "source_manifest_sha256": digest(manifest), "video_sha256": digest(destination / "episode.mp4"),
                       "ffmpeg_version": run([ffmpeg, "-version"]).decode().splitlines()[0]}
            if voice:
                receipt["voice_sha256"] = digest(destination / "voice.wav")
            (destination / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return receipt
    except BaseException:
        # Only this invocation's newly created directory can be removed.
        shutil.rmtree(destination)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        result = render(args.manifest, args.destination)
    except (ValueError, OSError, TypeError, KeyError):
        parser.exit(2, "Export impossible : vérifier le manifeste, les médias locaux et FFmpeg.\n")
    print(json.dumps({"exported": True, "duration_seconds": result["duration_seconds"], "audio": result["audio"]}))
