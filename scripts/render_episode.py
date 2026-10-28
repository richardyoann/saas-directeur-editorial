"""Offline, private slideshow export. No model calls, DB writes or publication."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from infrastructure.observability import mlflow_tracker
from infrastructure.process_env import child_environment

ARVOR_VIDEO_DURATION_SECONDS = 75
VIDEO_PROFILES = {
    # Historical offline preset: fast, no motion, kept reproducible for CI.
    "standard": {"width": 720, "height": 1280, "fps": 24, "ken_burns": False},
    # Editorial delivery preset: vertical 1080x1920, blurred fill, slow zoom
    # and a short fade between scenes. Rendering stays local FFmpeg only.
    "cinematic": {"width": 1080, "height": 1920, "fps": 24, "ken_burns": True},
}
CINEMATIC_FADE_SECONDS = 0.5


def validate_duration(total, *, arvor_75=False):
    """Validate the export preset before any output is created."""
    if total > 180:
        raise ValueError("episode_duration_invalid")
    if arvor_75 and total != ARVOR_VIDEO_DURATION_SECONDS:
        raise ValueError("arvor_75_duration_mismatch")



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


def run(command, cwd=None):
    try:
        return subprocess.run(command, check=True, capture_output=True, timeout=300,
                              env=child_environment(), cwd=cwd).stdout
    except (subprocess.SubprocessError, OSError):
        raise ValueError("media_command_failed") from None


def stamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def ass_stamp(seconds):
    centiseconds = round(seconds * 100)
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    seconds, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"


def ass_text(text):
    # SRT has no style escapes; ASS would otherwise interpret braces and
    # backslashes from a narration as override tags.
    return (text.replace("\\", "\\\\").replace("{", "\\{")
                .replace("}", "\\}").replace("\n", "\\N"))


def render(manifest, destination, *, arvor_75=False, telemetry=None,
           profile="standard"):
    manifest, destination = Path(manifest).resolve(), Path(destination).absolute()
    started = time.monotonic()
    if profile not in VIDEO_PROFILES:
        raise ValueError("video_profile_invalid")
    preset = VIDEO_PROFILES[profile]
    width, height, fps = preset["width"], preset["height"], preset["fps"]
    ken_burns = preset["ken_burns"]
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination_exists")
    if manifest.stat().st_size > 128000:
        raise ValueError("manifest_too_large")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != 1 or data.get("approved") is not True:
        raise ValueError("approved_manifest_required")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 6:
        raise ValueError("scene_count_invalid")
    assets, total = [], 0
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("scene_invalid")
        duration = scene.get("duration_seconds")
        narration = scene.get("narration")
        if type(duration) is not int or not 1 <= duration <= 180:
            raise ValueError("scene_duration_invalid")
        if not isinstance(narration, str) or not narration.strip() or len(narration) > 4000:
            raise ValueError("narration_invalid")
        assets.append(local_file(manifest.parent, scene.get("image"), ".png"))
        total += duration
    validate_duration(total, arvor_75=arvor_75)
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
            subtitles, dialogues, cursor = [], [], 0
            receipts = []
            fade = CINEMATIC_FADE_SECONDS
            for index, (scene, image) in enumerate(zip(scenes, assets), 1):
                copied = work / f"scene-{index}.png"
                shutil.copyfile(image, copied)
                receipts.append({"scene": index, "image_sha256": digest(copied), "duration_seconds": scene["duration_seconds"]})
                duration = scene["duration_seconds"]
                if ken_burns:
                    out_fade = max(0.0, duration - fade)
                    graph = (
                        "[0:v]split=2[bgs][fgs];"
                        f"[bgs]scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height},gblur=sigma=32,eq=brightness=-0.12[bg];"
                        f"[fgs]scale={width}:{width}:force_original_aspect_ratio=decrease,"
                        f"zoompan=z='min(zoom+0.0006,1.10)':x='iw/2-(iw/zoom/2)':"
                        f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{width}:fps={fps}[fg];"
                        "[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1,"
                        f"fade=t=in:st=0:d={fade},fade=t=out:st={out_fade}:d={fade},"
                        "format=yuv420p[v]"
                    )
                    clip_command = [ffmpeg, "-nostdin", "-v", "error", "-n", "-threads", "1",
                                    "-protocol_whitelist", "file,pipe", "-loop", "1",
                                    "-framerate", str(fps), "-i", str(copied),
                                    "-t", str(duration), "-filter_complex", graph,
                                    "-map", "[v]", "-r", str(fps), "-t", str(duration),
                                    "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast",
                                    "-pix_fmt", "yuv420p", str(work / f"clip-{index}.mp4")]
                else:
                    clip_command = [ffmpeg, "-nostdin", "-v", "error", "-n", "-threads", "1",
                                    "-protocol_whitelist", "file,pipe", "-f", "image2",
                                    "-c:v", "png", "-loop", "1", "-i", str(copied),
                                    "-t", str(duration),
                                    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                                           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                                    "-r", str(fps), "-c:v", "libx264", "-threads", "1",
                                    "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                                    str(work / f"clip-{index}.mp4")]
                run(clip_command)
                text = " ".join(scene["narration"].split())
                subtitles.append(f"{index}\n{stamp(cursor)} --> {stamp(cursor + duration)}\n{text}\n")
                dialogues.append(f"Dialogue: 0,{ass_stamp(cursor)},{ass_stamp(cursor + duration)},"
                                 f"Default,,0,0,0,,{ass_text(text)}")
                cursor += duration
            subtitle_text = "\n".join(subtitles)
            (work / "narration.srt").write_text(subtitle_text, encoding="utf-8")
            if ken_burns:
                # PlayRes makes FontSize/MarginV real output pixels. Without it
                # libass scales the SRT default 288-line script, producing huge
                # captions in the middle of a 1080x1920 video.
                ass = ("[Script Info]\nScriptType: v4.00+\n"
                       f"PlayResX: {width}\nPlayResY: {height}\n\n"
                       "[V4+ Styles]\n"
                       "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                       "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
                       "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
                       "MarginL, MarginR, MarginV, Encoding\n"
                       "Style: Default,DejaVu Sans,42,&H00FFFFFF,&H000000FF,&H00000000,"
                       "&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,60,60,220,1\n\n"
                       "[Events]\n"
                       "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
                       "Effect, Text\n" + "\n".join(dialogues) + "\n")
                (work / "narration.ass").write_text(ass, encoding="utf-8")
            (work / "clips.txt").write_text("".join(f"file 'clip-{i}.mp4'\n" for i in range(1, len(scenes) + 1)), encoding="utf-8")
            command = [ffmpeg, "-nostdin", "-v", "error", "-n", "-f", "concat", "-safe", "1", "-i", str(work / "clips.txt")]
            if voice:
                shutil.copyfile(voice, work / "voice.wav")
                command += ["-protocol_whitelist", "file,pipe", "-f", "wav", "-i", str(work / "voice.wav")]
            if ken_burns:
                # Burned captions make the delivered MP4 self-contained; the
                # sidecar SRT remains the machine-readable source.
                command += ["-vf", "subtitles=narration.ass", "-map", "0:v:0"]
                if voice:
                    command += ["-map", "1:a:0"]
                command += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                            "-pix_fmt", "yuv420p"]
                if voice:
                    command += ["-c:a", "aac"]
                command += ["-t", str(total), "-movflags", "+faststart",
                            str(destination / "episode.mp4")]
                run(command, cwd=work)
            else:
                if voice:
                    command += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-t", str(total)]
                command += ["-c:v", "copy", "-movflags", "+faststart",
                            str(destination / "episode.mp4")]
                run(command)
            probe = json.loads(run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(destination / "episode.mp4")]))
            if abs(float(probe["format"]["duration"]) - total) > 0.25:
                raise ValueError("export_duration_mismatch")
            (destination / "narration.srt").write_text(subtitle_text, encoding="utf-8")
            # A self-contained production folder preserves inputs for replay.
            for index in range(1, len(scenes) + 1):
                shutil.copyfile(work / f"scene-{index}.png", destination / f"scene-{index}.png")
                data["scenes"][index - 1]["image"] = f"scene-{index}.png"
            if voice:
                shutil.copyfile(work / "voice.wav", destination / "voice.wav")
                data["voice"] = "voice.wav"
            (destination / "production.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            receipt = {"schema_version": 1, "duration_seconds": total, "width": width, "height": height,
                       "fps": fps, "profile": profile, "ken_burns": ken_burns,
                       "transitions": "fade" if ken_burns else "cut",
                       "audio": bool(voice),
                       "subtitles": "sidecar+burned" if ken_burns else "sidecar", "scenes": receipts,
                       "source_manifest_sha256": digest(manifest), "video_sha256": digest(destination / "episode.mp4"),
                       "ffmpeg_version": run([ffmpeg, "-version"]).decode().splitlines()[0]}
            if voice:
                receipt["voice_sha256"] = digest(destination / "voice.wav")
            (destination / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    except BaseException:
        # Only this invocation's newly created directory can be removed.
        shutil.rmtree(destination)
        raise
    # Telemetry runs after the protected export block: even an unexpected
    # BaseException from the tracker can never delete a successful export.
    preproduction = data.get("preproduction") if isinstance(data.get("preproduction"), dict) else {}
    try:
        story_id = uuid.UUID(str(preproduction.get("run_id")))
    except (ValueError, TypeError):
        story_id = uuid.uuid5(uuid.NAMESPACE_URL, str(manifest))
    try:
        if callable(telemetry):
            # Caller-injected telemetry keeps the real tenant/story identity.
            telemetry(receipt)
        else:
            mlflow_tracker.record_export_receipt(
                receipt, tenant=uuid.uuid5(story_id, "offline-export-tenant"),
                story_id=story_id, encode_seconds=round(time.monotonic() - started, 3),
            )
    except BaseException:  # noqa: BLE001 - observability never invalidates an export
        pass
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--arvor-75", action="store_true",
                        help="Require an approved storyboard totaling exactly 75 seconds.")
    args = parser.parse_args()
    try:
        result = render(args.manifest, args.destination, arvor_75=args.arvor_75)
    except (ValueError, OSError, TypeError, KeyError):
        parser.exit(2, "Export impossible : vérifier le manifeste, les médias locaux et FFmpeg.\n")
    print(json.dumps({"exported": True, "duration_seconds": result["duration_seconds"], "audio": result["audio"]}))
