"""Offline Piper TTS -> one exact-length PCM WAV, aligned to approved scenes.

No network, model install, database, publication, overwrite or automatic retry.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import wave

from infrastructure.observability import mlflow_tracker
from infrastructure.process_env import child_environment

RATE = 24000
CHANNELS = 1
WIDTH = 2


def synthesize_voice(scenes, model, destination, *, piper="piper", ffmpeg="ffmpeg",
                     tenant=None, story_id=None):
    """Synthesize once, then publish best-effort, privacy-safe measurements."""
    started = time.monotonic()
    text = " ".join(scene.get("narration", "") for scene in scenes
                    if isinstance(scene, dict) and isinstance(scene.get("narration"), str))
    target = sum(scene.get("duration_seconds", 0) for scene in scenes
                 if isinstance(scene, dict) and type(scene.get("duration_seconds")) is int)
    surrogate = story_id or uuid.uuid5(uuid.NAMESPACE_URL, str(Path(destination).absolute()))
    try:
        surrogate_uuid = uuid.UUID(str(surrogate))
    except (TypeError, ValueError):
        surrogate_uuid = uuid.uuid5(uuid.NAMESPACE_URL, str(surrogate))
    tenant_ref = tenant or uuid.uuid5(surrogate_uuid, "offline-voice-tenant")
    try:
        result = _synthesize_voice(scenes, model, destination, piper=piper, ffmpeg=ffmpeg)
    except ValueError as error:
        mlflow_tracker.record_voice(
            tenant=tenant_ref, story_id=surrogate_uuid, engine="piper",
            voice=Path(str(model)).name, text=text, status="failed",
            error_code=str(error), target_seconds=target,
            generation_seconds=round(time.monotonic() - started, 3),
        )
        raise
    mlflow_tracker.record_voice(
        tenant=tenant_ref, story_id=surrogate_uuid, engine="piper",
        voice=Path(str(model)).name, text=text, status="ready",
        audio_sha256=result["voice_sha256"],
        byte_count=result.get("byte_count"),
        audio_seconds=result["duration_seconds"], target_seconds=target,
        generation_seconds=round(time.monotonic() - started, 3),
    )
    return result


def _synthesize_voice(scenes, model, destination, *, piper="piper", ffmpeg="ffmpeg"):
    """Synthesize each narration, pad each scene; reject speech that exceeds its slot."""
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 6:
        raise ValueError("voice_scenes_invalid")
    total = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("voice_scene_invalid")
        duration, text = scene.get("duration_seconds"), scene.get("narration")
        if type(duration) is not int or not 1 <= duration <= 75:
            raise ValueError("voice_scene_duration_invalid")
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("voice_narration_invalid")
        total += duration
    if total != 75:
        raise ValueError("voice_duration_not_75")
    model = Path(model).absolute()
    if (model.suffix != ".onnx" or model.is_symlink() or not model.is_file()
            or model.stat().st_size == 0):
        raise ValueError("piper_model_unavailable")
    binary = shutil.which(piper)
    converter = shutil.which(ffmpeg)
    if not binary or not converter:
        raise ValueError("piper_or_ffmpeg_unavailable")
    target = Path(destination).absolute()
    if target.suffix.lower() != ".wav" or target.is_symlink() or target.exists():
        raise ValueError("voice_destination_invalid")
    if (not target.parent.is_dir() or
            any(p.is_symlink() for p in (target.parent, *target.parent.parents))):
        raise ValueError("voice_private_directory_invalid")
    # Media binaries never inherit telemetry or application credentials.
    environment = child_environment()
    # The intermediate audio is private and discarded even on failure.
    segments = []
    with tempfile.TemporaryDirectory(prefix=".tts-", dir=target.parent) as temp:
        work = Path(temp)
        for index, scene in enumerate(scenes):
            intermediate = work / f"{index}.wav"
            pcm = work / f"{index}.pcm"
            try:
                subprocess.run([binary, "--model", str(model), "--output_file", str(intermediate)],
                               input=(scene["narration"].strip() + "\n").encode("utf-8"),
                               capture_output=True, timeout=120, check=True,
                               env=environment)
                if not intermediate.is_file() or intermediate.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("tts_output_invalid")
                subprocess.run([converter, "-nostdin", "-v", "error", "-y", "-i",
                                str(intermediate), "-f", "s16le", "-ar", str(RATE),
                                "-ac", "1", str(pcm)], capture_output=True,
                               timeout=60, check=True, env=environment)
            except (OSError, subprocess.SubprocessError):
                raise ValueError("tts_engine_failed") from None
            if not pcm.is_file() or pcm.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("tts_output_invalid")
            audio = pcm.read_bytes()
            slot_bytes = scene["duration_seconds"] * RATE * WIDTH
            if not audio or not any(audio) or len(audio) % WIDTH:
                raise ValueError("tts_audio_empty_or_invalid")
            if len(audio) > slot_bytes:
                raise ValueError("tts_scene_too_long")
            segments.append(audio + bytes(slot_bytes - len(audio)))
        # Atomic creation: never overwrite an existing voice file.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(target, flags, 0o600)
        except FileExistsError:
            raise ValueError("voice_destination_exists") from None
        try:
            with os.fdopen(fd, "wb") as output:
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(CHANNELS)
                    wav.setsampwidth(WIDTH)
                    wav.setframerate(RATE)
                    for segment in segments:
                        wav.writeframesraw(segment)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    return {"voice_created": True, "duration_seconds": total,
            "sample_rate": RATE, "scene_count": len(scenes),
            "voice_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "byte_count": target.stat().st_size}
