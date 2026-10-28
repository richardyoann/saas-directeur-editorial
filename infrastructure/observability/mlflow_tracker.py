"""Best-effort MLflow telemetry for Arvor generation paths.

Design rules
------------
* PostgreSQL remains the single source of truth. A tracking failure never
  changes a generation outcome and never raises into the caller.
* Only measurements and pseudonymous identifiers leave Arvor: prompt/response
  text is hashed or counted, never logged. Tenant ids are hashed as well.
* Tracking is opt-in (``ARVOR_MLFLOW_ENABLED=true``) and the tracking server
  must be loopback-only.
* Publishing happens on one bounded background thread so a slow or stopped
  server cannot delay a generation. When a publish fails, the event is kept in
  a bounded local spool and can be replayed once; replay is idempotent thanks
  to a deterministic ``arvor_event_id`` tag.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import queue
import re
import stat
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

try:  # POSIX (WSL/Linux); Windows is out of scope for the private runtime.
    import fcntl
except ImportError:  # pragma: no cover - keeps imports portable for tests
    fcntl = None

MAX_TEXT_BYTES = 262144
MAX_QUEUE = 64
MAX_SPOOL_BYTES = 5 * 1024 * 1024
MAX_VALUE_CHARS = 500
MAX_FLOAT = 1e12
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,119}\Z")
KEY = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

EXPERIMENTS = {
    "scenario": "arvor-scenario-generation",
    "image": "arvor-image-generation",
    "voice": "arvor-voice-generation",
    "video": "arvor-video-generation",
}
NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

PARAM_KEYS = frozenset({
    "adapter", "model", "prompt_version", "workflow_version", "code_version",
    "engine", "voice", "preset", "resolution", "output_format", "codec",
    "max_tokens", "temperature", "stream", "ffmpeg_version", "audio",
    "scene_count", "fps",
})
METRIC_KEYS = frozenset({
    "duration_seconds", "generation_seconds", "encode_seconds", "prompt_chars",
    "output_chars", "text_chars", "prompt_tokens", "completion_tokens",
    "total_tokens", "width", "height", "byte_count", "audio_seconds",
    "target_seconds", "real_seconds", "scene_count", "fps",
})
TAG_KEYS = frozenset({
    "arvor_kind", "arvor_story_id", "arvor_scene_id", "arvor_asset_id",
    "arvor_step", "arvor_status", "arvor_error_code", "arvor_tenant_sha256",
    "arvor_prompt_sha256", "arvor_output_sha256", "arvor_png_sha256",
    "arvor_audio_sha256", "arvor_video_sha256", "arvor_storage_ref_sha256",
    "arvor_code_version", "arvor_trace_id",
})
FORBIDDEN_KEYS = frozenset({
    "prompt", "response", "content", "text", "narration", "tenant", "actor",
    "password", "secret", "token", "credentials",
})
# Traces have their own strict allowlist: a trace payload can never become a
# free-form channel for business content.
TRACE_KEYS = frozenset({
    "prompt_sha256", "prompt_chars", "output_chars", "text_sha256", "text_chars",
    "status", "error_code", "finish", "width", "height", "audio_seconds",
    "real_seconds", "scene_count", "target_seconds", "model",
    "duration_seconds", "engine", "ffmpeg_version",
})


class TrackerConfigurationError(ValueError):
    """Raised only by explicit configuration checks, never by recording."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def _loopback_uri(value: str) -> str:
    """Accept only an explicit loopback HTTP(S) endpoint without path/query."""
    value = (value or "").strip()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError()
        if parsed.port is None or not 1 <= parsed.port <= 65535:
            raise ValueError()
        host = parsed.hostname.lower()
        if host == "localhost":
            return value.rstrip("/")
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError()
    except ValueError:
        raise TrackerConfigurationError("mlflow_tracking_uri_must_be_loopback") from None
    return value.rstrip("/")


def code_version() -> str:
    value = os.getenv("ARVOR_CODE_VERSION", "").strip()
    if value and re.fullmatch(r"[A-Za-z0-9._+-]{1,64}", value):
        return value
    return "unknown"


def _configuration():
    if os.getenv("ARVOR_MLFLOW_ENABLED", "").strip().lower() != "true":
        return None
    try:
        uri = _loopback_uri(os.getenv("MLFLOW_TRACKING_URI", ""))
    except TrackerConfigurationError:
        return None
    spool = os.getenv("ARVOR_MLFLOW_SPOOL", "").strip()
    if spool:
        try:
            spool_path = Path(spool)
            if not spool_path.is_absolute():
                spool = ""
        except (OSError, ValueError):
            spool = ""
    # Credentials are read by the MLflow client from its own environment
    # (MLFLOW_TRACKING_USERNAME/PASSWORD). The tracker never copies them into
    # os.environ, so child processes such as ffmpeg/piper cannot inherit them.
    return {"uri": uri, "spool": spool, "code_version": code_version()}


def configured_uri(value: str) -> str:
    """Public, testable helper used by the health-check script."""
    return _loopback_uri(value)


# --------------------------------------------------------------------------
# Sanitisation and event validation
# --------------------------------------------------------------------------

def sha256_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def sanitize_model(value) -> str:
    """Keep a technical model identifier, never an arbitrary provider string."""
    if not isinstance(value, str):
        return "unknown"
    name = re.split(r"[\\/]", value.strip())[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    return name if MODEL_NAME.fullmatch(name) else "unknown"


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("metric_type")
    value = float(value)
    if not math.isfinite(value) or abs(value) > MAX_FLOAT or value < 0:
        raise ValueError("metric_range")
    return value


def _validate(event: dict) -> dict:
    kind = event.get("kind")
    if kind not in EXPERIMENTS:
        raise ValueError("event_kind")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not UUID_TEXT.fullmatch(event_id):
        raise ValueError("event_id")
    allowed = {"kind", "event_id", "experiment", "run_name", "params",
               "metrics", "tags", "trace"}
    if set(event) - allowed:
        raise ValueError("event_shape")
    if event.get("experiment") != EXPERIMENTS[kind]:
        raise ValueError("experiment")
    if not isinstance(event.get("run_name"), str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,63}", event["run_name"]):
        raise ValueError("run_name")
    params, metrics, tags = event.get("params", {}), event.get("metrics", {}), event.get("tags", {})
    if set(params) - PARAM_KEYS or set(metrics) - METRIC_KEYS or set(tags) - TAG_KEYS:
        raise ValueError("unknown_key")
    if set(params) & FORBIDDEN_KEYS or set(tags) & FORBIDDEN_KEYS:
        raise ValueError("forbidden_key")
    clean = {"kind": kind, "event_id": event_id,
             "experiment": event["experiment"], "run_name": event["run_name"],
             "params": {}, "metrics": {}, "tags": {}, "trace": {}}
    for key, value in params.items():
        if not KEY.fullmatch(key) or not isinstance(value, str):
            raise ValueError("param")
        text = value.strip()
        if not text or len(text) > MAX_VALUE_CHARS or any(ord(ch) < 32 for ch in text):
            raise ValueError("param")
        clean["params"][key] = text
    for key, value in metrics.items():
        if not KEY.fullmatch(key):
            raise ValueError("metric")
        clean["metrics"][key] = _number(value)
    for key, value in tags.items():
        if not KEY.fullmatch(key) or not isinstance(value, str):
            raise ValueError("tag")
        text = value.strip()
        if not text or len(text) > MAX_VALUE_CHARS or any(ord(ch) < 32 for ch in text):
            raise ValueError("tag")
        clean["tags"][key] = text
    for key in ("arvor_story_id", "arvor_scene_id", "arvor_asset_id"):
        if key in clean["tags"] and not UUID_TEXT.fullmatch(clean["tags"][key].lower()):
            raise ValueError("tag_uuid")
    trace = event.get("trace") or {}
    if set(trace) - {"name", "inputs", "outputs", "attributes"}:
        raise ValueError("trace_shape")
    trace_name = str(trace.get("name") or f"arvor.{kind}")[:64]
    if not re.fullmatch(r"arvor\.[a-z0-9_.-]{1,57}", trace_name):
        raise ValueError("trace_name")
    clean["trace"] = {
        "name": trace_name,
        "inputs": _safe_trace_mapping(trace.get("inputs")),
        "outputs": _safe_trace_mapping(trace.get("outputs")),
        "attributes": _safe_trace_mapping(trace.get("attributes")),
    }
    return clean


def _safe_trace_mapping(value) -> dict:
    """Strict trace allowlist: only measurements, never free-form business text."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError("trace_mapping")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or key not in TRACE_KEYS or key in FORBIDDEN_KEYS:
            raise ValueError("trace_key")
        if item is None:
            continue
        if isinstance(item, bool):
            result[key] = item
        elif isinstance(item, (int, float)) and math.isfinite(float(item)):
            result[key] = item
        elif isinstance(item, str):
            text = item.strip()
            if len(text) <= 200 and not any(ord(ch) < 32 for ch in text):
                result[key] = text
        else:
            raise ValueError("trace_value")
    return result


def event_id(kind: str, key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"arvor:{kind}:{key}"))


def _run_name(kind: str, suffix: str) -> str:
    return (kind + "-" + re.sub(r"[^a-z0-9]+", "-", suffix.lower()).strip("-"))[:64]


def _base_tags(kind, tenant, status, error_code, extra=None):
    tags = {"arvor_kind": kind, "arvor_status": status,
            "arvor_tenant_sha256": sha256_text(str(tenant))}
    if error_code:
        tags["arvor_error_code"] = str(error_code)[:120]
    tags.update(extra or {})
    tags["arvor_code_version"] = code_version()
    return tags


# --------------------------------------------------------------------------
# Event builders (the only sanctioned way to publish telemetry)
# --------------------------------------------------------------------------

def scenario_event(*, tenant, story_id, step, prompt, response, status,
                   error_code=None, prompt_version=None, workflow_version=None,
                   model=None, usage=None, duration_seconds=None,
                   max_tokens=None, temperature=None, stream=False):
    prompt = prompt if isinstance(prompt, str) else ""
    output = response if isinstance(response, str) else ""
    prompt_sha = sha256_text(prompt)
    usage = usage if isinstance(usage, dict) else {}
    metrics = {"prompt_chars": float(len(prompt)), "output_chars": float(len(output))}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000_000:
            metrics[key] = float(value)
    if duration_seconds is not None:
        metrics["duration_seconds"] = _number(duration_seconds)
    params = {"adapter": "llama.cpp", "model": sanitize_model(model), "stream": "true" if stream else "false"}
    if prompt_version:
        params["prompt_version"] = str(prompt_version)[:64]
    if workflow_version:
        params["workflow_version"] = str(workflow_version)[:64]
    if max_tokens is not None:
        params["max_tokens"] = str(int(max_tokens))
    if temperature is not None:
        params["temperature"] = str(float(temperature))
    tags = _base_tags("scenario", tenant, status, error_code, {
        "arvor_story_id": str(story_id), "arvor_step": str(step),
        "arvor_prompt_sha256": prompt_sha,
        "arvor_output_sha256": sha256_text(output) if output else "",
    })
    tags = {k: v for k, v in tags.items() if v}
    return {"kind": "scenario", "experiment": EXPERIMENTS["scenario"],
            "event_id": event_id("scenario", f"{story_id}:{step}:{prompt_sha}"),
            "run_name": _run_name("scenario", f"{step}-{story_id}"),
            "params": params, "metrics": metrics, "tags": tags,
            "trace": {"name": f"arvor.scenario.{step}",
                      "inputs": {"prompt_sha256": prompt_sha, "prompt_chars": len(prompt)},
                      "outputs": {"status": status, "output_chars": len(output),
                                  "error_code": error_code or "",
                                  "finish": "stop" if status == "success" else "error"},
                      "attributes": {"model": params["model"],
                                     "duration_seconds": metrics.get("duration_seconds")}}}


def image_event(*, tenant, story_id, scene_id, asset_id=None, prompt, status,
                error_code=None, model=None, width=None, height=None,
                duration_seconds=None, png_sha256=None, byte_count=None,
                storage_ref=None, resolution=None, output_format="png"):
    prompt = prompt if isinstance(prompt, str) else ""
    prompt_sha = sha256_text(prompt)
    metrics = {}
    for key, value in (("width", width), ("height", height),
                       ("byte_count", byte_count)):
        if value is not None:
            metrics[key] = _number(value)
    if duration_seconds is not None:
        metrics["duration_seconds"] = _number(duration_seconds)
    tags = _base_tags("image", tenant, status, error_code, {
        "arvor_story_id": str(story_id), "arvor_scene_id": str(scene_id),
        "arvor_prompt_sha256": prompt_sha,
        "arvor_png_sha256": png_sha256 or "",
        "arvor_storage_ref_sha256": sha256_text(storage_ref) if storage_ref else "",
    })
    if asset_id:
        tags["arvor_asset_id"] = str(asset_id)
    tags = {k: v for k, v in tags.items() if v}
    return {"kind": "image", "experiment": EXPERIMENTS["image"],
            "event_id": event_id("image", f"{story_id}:{scene_id}:{png_sha256 or error_code or status}"),
            "run_name": _run_name("image", f"{scene_id}"),
            "params": {"adapter": "sdcpp-http", "model": sanitize_model(model),
                       "resolution": resolution or "unknown",
                       "output_format": output_format or "unknown"},
            "metrics": metrics, "tags": tags,
            "trace": {"name": "arvor.image.generate",
                      "inputs": {"prompt_sha256": prompt_sha, "prompt_chars": len(prompt)},
                      "outputs": {"status": status, "error_code": error_code or "",
                                  "width": width, "height": height},
                      "attributes": {"model": sanitize_model(model),
                                     "duration_seconds": duration_seconds}}}


def voice_event(*, tenant, story_id, asset_id=None, engine=None, voice=None,
                text="", status="ready", error_code=None, audio_sha256=None,
                byte_count=None, audio_seconds=None, target_seconds=None,
                generation_seconds=None):
    text = text if isinstance(text, str) else ""
    metrics = {"text_chars": float(len(text))}
    for key, value in (("byte_count", byte_count), ("audio_seconds", audio_seconds),
                       ("target_seconds", target_seconds),
                       ("generation_seconds", generation_seconds)):
        if value is not None:
            metrics[key] = _number(value)
    tags = _base_tags("voice", tenant, status, error_code, {
        "arvor_story_id": str(story_id),
        "arvor_audio_sha256": audio_sha256 or "",
    })
    if asset_id:
        tags["arvor_asset_id"] = str(asset_id)
    tags = {k: v for k, v in tags.items() if v}
    return {"kind": "voice", "experiment": EXPERIMENTS["voice"],
            "event_id": event_id("voice", f"{story_id}:{asset_id}:{audio_sha256 or error_code or status}"),
            "run_name": _run_name("voice", f"{story_id}"),
            "params": {"engine": str(engine or "unknown")[:64],
                       "voice": str(voice or "unknown")[:64]},
            "metrics": metrics, "tags": tags,
            "trace": {"name": "arvor.voice.generate",
                      "inputs": {"text_sha256": sha256_text(text), "text_chars": len(text)},
                      "outputs": {"status": status, "error_code": error_code or "",
                                  "audio_seconds": audio_seconds},
                      "attributes": {"engine": str(engine or "unknown")[:64]}}}


def video_event(*, tenant, story_id, asset_id=None, scene_count, target_seconds,
                real_seconds=None, status="exported", error_code=None,
                video_sha256=None, byte_count=None, encode_seconds=None,
                ffmpeg_version=None, audio=False, fps=24, resolution="720x1280"):
    metrics = {"scene_count": _number(scene_count)}
    for key, value in (("target_seconds", target_seconds), ("real_seconds", real_seconds),
                       ("byte_count", byte_count), ("encode_seconds", encode_seconds)):
        if value is not None:
            metrics[key] = _number(value)
    tags = _base_tags("video", tenant, status, error_code, {
        "arvor_story_id": str(story_id),
        "arvor_video_sha256": video_sha256 or "",
    })
    if asset_id:
        tags["arvor_asset_id"] = str(asset_id)
    tags = {k: v for k, v in tags.items() if v}
    version = (ffmpeg_version or "").splitlines()[0][:120] if ffmpeg_version else "unknown"
    return {"kind": "video", "experiment": EXPERIMENTS["video"],
            "event_id": event_id("video", f"{story_id}:{asset_id}:{video_sha256 or error_code or status}"),
            "run_name": _run_name("video", f"{story_id}"),
            "params": {"preset": "arvor-75" if target_seconds == 75 else "slideshow",
                       "resolution": resolution, "codec": "h264", "fps": str(fps),
                       "audio": "true" if audio else "false",
                       "ffmpeg_version": version},
            "metrics": metrics, "tags": tags,
            "trace": {"name": "arvor.video.export",
                      "inputs": {"scene_count": scene_count, "target_seconds": target_seconds},
                      "outputs": {"status": status, "error_code": error_code or "",
                                  "real_seconds": real_seconds},
                      "attributes": {"ffmpeg_version": version}}}


# --------------------------------------------------------------------------
# Publication (background, bounded, fail-open)
# --------------------------------------------------------------------------

def _import_mlflow():
    import mlflow  # noqa: PLC0415 - optional dependency, imported lazily
    return mlflow


_publish_lock = threading.Lock()


def _lock_spool(path):
    """Cross-process lock for the bounded spool (append and replay)."""
    fd = os.open(str(path) + ".lock",
                 os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    handle = os.fdopen(fd, "a+", encoding="utf-8")
    os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _unlock_spool(handle):
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _publish(event: dict, config: dict, mlflow_module=None) -> bool:
    """Publish one event. Returns False on any failure; never raises."""
    try:
        event = _validate(event)
    except (ValueError, TypeError):
        return False
    try:
        mlflow = mlflow_module or _import_mlflow()
        mlflow.set_tracking_uri(config["uri"])
        from mlflow.entities import Metric, Param, RunTag  # noqa: PLC0415
        client = mlflow.MlflowClient()
        experiment = client.get_experiment_by_name(event["experiment"])
        experiment_id = (client.create_experiment(event["experiment"])
                         if experiment is None else experiment.experiment_id)
        existing = None
        # Within one process, make search+create atomic so the daemon thread and
        # an explicit --replay cannot both create the same event.
        with _publish_lock:
            existing = client.search_runs(
                [experiment_id],
                filter_string=f"tags.`arvor_event_id` = '{event['event_id']}'",
                max_results=1,
            )
            if existing:
                return True
            tags = dict(event["tags"])
            tags["arvor_event_id"] = event["event_id"]
            run = client.create_run(experiment_id, run_name=event["run_name"], tags=tags)
        stamp = int(time.time() * 1000)
        client.log_batch(
            run.info.run_id,
            metrics=[Metric(key, value, stamp, 0) for key, value in event["metrics"].items()],
            params=[Param(key, value) for key, value in event["params"].items()],
            tags=[RunTag(key, value) for key, value in tags.items()],
        )
        _publish_trace(mlflow, client, run.info.run_id, event)
        terminal = "FINISHED" if event["tags"]["arvor_status"] in {
            "success", "ready", "exported",
        } else "FAILED"
        client.set_terminated(run.info.run_id, status=terminal)
        return True
    except Exception:  # noqa: BLE001 - telemetry must never break a generation
        return False


def _publish_trace(mlflow, client, run_id: str, event: dict) -> None:
    trace = event["trace"]
    try:
        # Manual tracing: the real clients are raw HTTP adapters, so autolog
        # would not capture the actual call. Only hashes/counters are recorded.
        with mlflow.start_span(name=trace["name"], run_id=run_id) as span:
            span.set_inputs(trace["inputs"])
            span.set_outputs(trace["outputs"])
            if trace["attributes"]:
                span.set_attributes(trace["attributes"])
            trace_id = getattr(span, "trace_id", None)
        # The span artifact is exported asynchronously: flush it before the run
        # is reported as finished so an immediate read is never "corrupted".
        flush = getattr(mlflow, "flush_trace_async_logging", None)
        if flush is not None:
            flush()
        if trace_id:
            client.set_tag(run_id, "arvor_trace_id", str(trace_id))
    except Exception:  # noqa: BLE001 - a missing span must not lose the run
        pass


class _Sink:
    """One daemon thread, bounded queue, local spool on failure."""

    def __init__(self, config: dict):
        self.config = config
        self.queue = queue.Queue(maxsize=MAX_QUEUE)
        self.lock = threading.Lock()
        self.thread = None
        self.stats = {"published": 0, "failed": 0, "spooled": 0, "dropped": 0}

    def start(self):
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, name="arvor-mlflow",
                                               daemon=True)
                self.thread.start()

    def submit(self, event: dict) -> str:
        if self.config is None:
            return "disabled"
        try:
            event = _validate(event)
        except (ValueError, TypeError):
            self._count("dropped")
            return "dropped"
        self.start()
        try:
            self.queue.put_nowait(event)
            return "queued"
        except queue.Full:
            if self._spool(event):
                self._count("spooled")
                return "spooled"
            self._count("dropped")
            return "dropped"

    def _count(self, name):
        with self.lock:
            self.stats[name] += 1

    def _run(self):
        while True:
            try:
                event = self.queue.get(timeout=60)
            except queue.Empty:
                self._replay()
                continue
            try:
                if _publish(event, self.config):
                    self._count("published")
                elif self._spool(event):
                    self._count("failed")
                else:
                    self._count("failed")
            finally:
                self.queue.task_done()

    def _replay(self):
        """Retry the bounded spool once a minute while the worker is idle."""
        path = self.config.get("spool") if self.config else ""
        if not path:
            return
        try:
            if not Path(path).exists() or not Path(path).stat().st_size:
                return
            flush_spool(5)
        except BaseException:  # noqa: BLE001 - never kill the telemetry thread
            return

    def _spool(self, event: dict) -> bool:
        path = self.config.get("spool") if self.config else ""
        if not path:
            return False
        try:
            target = Path(path)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            payload = (line + "\n").encode("utf-8")
            if len(payload) > MAX_TEXT_BYTES:
                return False
            lock = _lock_spool(target)
            try:
                # Check the projected size under the same lock as the append so
                # the announced 5 MiB bound is strict even with concurrent writers.
                # A pre-existing symlink would redirect pseudonymised events
                # outside the private spool; refuse it and never follow it.
                if target.is_symlink():
                    return False
                size = target.stat().st_size if target.exists() else 0
                if size + len(payload) > MAX_SPOOL_BYTES:
                    return False
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
                return True
            finally:
                _unlock_spool(lock)
        except OSError:
            return False

    def flush(self, timeout=5.0):
        deadline = time.monotonic() + max(0.0, timeout)
        while self.queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)


_sink = None
_sink_lock = threading.Lock()


def _get_sink():
    global _sink
    config = _configuration()
    if config is None:
        return None
    with _sink_lock:
        if _sink is None or _sink.config != config:
            _sink = _Sink(config)
        return _sink


def submit(event: dict) -> str:
    """Queue one event. Never raises; returns disabled/queued/spooled/dropped."""
    try:
        sink = _get_sink()
        if sink is None:
            return "disabled"
        return sink.submit(event)
    except Exception:  # noqa: BLE001
        return "dropped"


def flush(timeout=5.0) -> None:
    sink = _get_sink()
    if sink is not None:
        sink.flush(timeout)


def stats() -> dict:
    sink = _get_sink()
    return dict(sink.stats) if sink is not None else {}


def reset() -> None:
    """Test helper: forget the current sink (the daemon thread drains itself)."""
    global _sink
    with _sink_lock:
        _sink = None


def spool_path() -> str:
    config = _configuration()
    return (config or {}).get("spool", "")


def _append_spool(path: Path, payload: bytes) -> None:
    lock = _lock_spool(path)
    try:
        if path.is_symlink():
            raise OSError("spool_symlink_forbidden")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        _unlock_spool(lock)


def flush_spool(timeout=15.0) -> dict:
    """Replay the local spool once. Idempotent: existing event ids are skipped.

    The spool is claimed by an atomic rename before publishing, so events
    appended by the daemon during the replay land in a new file and cannot be
    overwritten. Failures are merged back under a cross-process lock.
    """
    config = _configuration()
    if config is None or not config.get("spool"):
        return {"replayed": 0, "failed": 0, "skipped": 0, "error": "disabled"}
    path = Path(config["spool"])
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = _lock_spool(path)
    except OSError:
        return {"replayed": 0, "failed": 0, "skipped": 0, "error": "locked"}
    claimed = path.with_name(f"{path.name}.{uuid.uuid4().hex}.replay")
    try:
        if not path.exists():
            return {"replayed": 0, "failed": 0, "skipped": 0, "error": ""}
        os.replace(path, claimed)
    except OSError:
        return {"replayed": 0, "failed": 0, "skipped": 0, "error": "claim"}
    finally:
        _unlock_spool(lock)
    replayed = failed = skipped = 0
    remaining = []
    deadline = time.monotonic() + max(1.0, timeout)
    try:
        lines = claimed.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        try:
            _append_spool(path, claimed.read_bytes())
        except OSError:
            return {"replayed": 0, "failed": 0, "skipped": 0, "error": "unreadable"}
        claimed.unlink(missing_ok=True)
        return {"replayed": 0, "failed": 0, "skipped": 0, "error": "unreadable"}
    for line in lines:
        if not line.strip():
            continue
        if time.monotonic() > deadline:
            remaining.append(line)
            continue
        try:
            event = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if _publish(event, config):
            replayed += 1
        else:
            remaining.append(line)
            failed += 1
    try:
        if remaining:
            _append_spool(path, ("\n".join(remaining) + "\n").encode("utf-8"))
        claimed.unlink(missing_ok=True)
    except OSError:
        return {"replayed": replayed, "failed": failed, "skipped": skipped,
                "error": "rewrite"}
    return {"replayed": replayed, "failed": failed, "skipped": skipped, "error": ""}


# --------------------------------------------------------------------------
# Convenience wrappers used by business code. They never raise.
# --------------------------------------------------------------------------

def record(event: dict) -> str:
    try:
        return submit(event)
    except Exception:  # noqa: BLE001
        return "dropped"


def record_scenario_step(**kwargs):
    try:
        return record(scenario_event(**kwargs))
    except Exception:  # noqa: BLE001
        return "dropped"


def record_image(**kwargs):
    try:
        return record(image_event(**kwargs))
    except Exception:  # noqa: BLE001
        return "dropped"


def record_voice(**kwargs):
    try:
        return record(voice_event(**kwargs))
    except Exception:  # noqa: BLE001
        return "dropped"


def record_video(**kwargs):
    try:
        return record(video_event(**kwargs))
    except Exception:  # noqa: BLE001
        return "dropped"


def record_export_receipt(receipt: dict, *, tenant, story_id, asset_id=None,
                          encode_seconds=None) -> str:
    """Instrument the offline FFmpeg export from its signed receipt."""
    try:
        receipt = receipt if isinstance(receipt, dict) else {}
        scenes = receipt.get("scenes") if isinstance(receipt.get("scenes"), list) else []
        real = receipt.get("duration_seconds")
        voice_sha = receipt.get("voice_sha256")
        status = "exported"
        video = record_video(
            tenant=tenant, story_id=story_id, asset_id=asset_id,
            scene_count=len(scenes), target_seconds=float(real or 0),
            real_seconds=float(real or 0), status=status,
            video_sha256=receipt.get("video_sha256"),
            byte_count=None, encode_seconds=encode_seconds,
            ffmpeg_version=receipt.get("ffmpeg_version"),
            audio=bool(receipt.get("audio")), fps=receipt.get("fps", 24),
            resolution=f"{receipt.get('width', 720)}x{receipt.get('height', 1280)}",
        )
        voice = "disabled"
        if voice_sha:
            voice = record_voice(
                tenant=tenant, story_id=story_id, asset_id=asset_id,
                engine="external-wav", voice="unknown",
                text="", status="ready", audio_sha256=voice_sha,
                audio_seconds=float(real or 0), target_seconds=float(real or 0),
            )
        return video if voice == "disabled" else f"{video}/{voice}"
    except Exception:  # noqa: BLE001
        return "dropped"
