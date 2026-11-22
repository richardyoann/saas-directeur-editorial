"""OpenCode JSONL telemetry observer; never a CI, merge, or delivery authority.

This module reads OpenCode `run --format json` JSONL events and records only
bounded numeric counters in a private loopback MLflow server. It never exports
prompts, responses, tool arguments/results, session identifiers, secrets, or
raw logs. A telemetry failure is reported as unavailable and must not affect
any mission, gate, or delivery decision.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

SHA = re.compile(r"[a-fA-F0-9]{40}\Z")
KEYS = (
    "events_total",
    "content_events",
    "tool_events",
    "error_events",
    "step_events",
    "other_events",
)
MAX_LINE = 1_048_576
MAX_BYTES = 33_554_432
MAX_EVENTS = 50_000


class StreamLimitError(ValueError):
    """Input exceeded a hard bound; the message is a fixed code."""


def loopback_tracking_uri(value: str) -> str:
    """Allow only an explicit HTTP loopback MLflow URI."""
    value = value.strip()
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme != "http"
            or not host
            or port is None
            or not 1 <= port <= 65535
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError()
        if host.lower() == "localhost":
            return value.rstrip("/")
        address = ipaddress.ip_address(host)
        if not address.is_loopback:
            raise ValueError()
    except ValueError:
        raise ValueError("invalid_private_configuration") from None
    return value.rstrip("/")


def _category(kind: object) -> str:
    if kind in ("text", "reasoning", "message", "message.part.updated"):
        return "content_events"
    if isinstance(kind, str) and (
        kind.startswith("tool.") or kind in {"tool_use", "tool_call", "tool_result", "tool"}
    ):
        return "tool_events"
    if isinstance(kind, str) and (kind.endswith(".error") or kind == "error"):
        return "error_events"
    if isinstance(kind, str) and kind.startswith("step"):
        return "step_events"
    return "other_events"


def summarize(stream) -> dict[str, int]:
    """Count event categories without retaining event content."""
    counts = Counter()
    total = 0
    while True:
        line = stream.readline(MAX_LINE + 1)
        if not line:
            break
        total += len(line)
        if len(line) > MAX_LINE or total > MAX_BYTES:
            raise StreamLimitError("stream_limit")
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            raise ValueError("invalid_json") from None
        if not isinstance(event, dict):
            raise ValueError("invalid_shape")
        counts["events_total"] += 1
        if counts["events_total"] > MAX_EVENTS:
            raise StreamLimitError("too_many_events")
        counts[_category(event.get("type"))] += 1
    if not counts["events_total"]:
        raise ValueError("empty_stream")
    return {key: int(counts[key]) for key in KEYS}


def _open_input(path: Path):
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if path.is_symlink():
        raise ValueError("invalid_input")
    fd = os.open(path, flags | nofollow)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("invalid_input")
        if info.st_size > MAX_BYTES:
            raise ValueError("invalid_input")
        return os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise


def load_input(path_arg: str) -> dict[str, int]:
    if path_arg == "-":
        return summarize(sys.stdin.buffer)
    path = Path(path_arg)
    if not path.exists():
        raise ValueError("invalid_input")
    with _open_input(path) as source:
        return summarize(source)


def publish(mlflow, uri: str, sha: str, pr: int | None, counts: dict[str, int]) -> str:
    """Publish only allowlisted metadata; caller handles all exceptions."""
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("arvor-opencode-observability-poc")
    with mlflow.start_run(run_name="opencode-jsonl-observation") as run:
        # SHA is operator-declared metadata, not verified by this bridge.
        mlflow.log_param("commit_sha_declared", sha.lower())
        mlflow.set_tag("commit_sha_verified", "false")
        if pr is not None:
            mlflow.log_param("pr_number", int(pr))
        mlflow.set_tag("trust_level", "unverified_observability")
        mlflow.set_tag("merge_or_deploy_authorized", "false")
        mlflow.set_tag("ci_gate", "false")
        for key in KEYS:
            mlflow.log_metric(key, int(counts[key]))
        return str(run.info.run_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True, help="Declared commit SHA (not verified).")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--input", default="-")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    if not SHA.fullmatch(args.sha) or (args.pr is not None and args.pr < 1):
        print(json.dumps({"status": "invalid_metadata"}, sort_keys=True))
        return 2
    try:
        counts = load_input(args.input)
    except (OSError, ValueError, StreamLimitError):
        print(json.dumps({"status": "invalid_event_stream"}, sort_keys=True))
        return 2

    result = {"status": "observed_only", "quality_gate": "not_evaluated", **counts}
    if not args.execute:
        print(json.dumps(result, sort_keys=True))
        return 0

    try:
        uri = loopback_tracking_uri(os.getenv("ARVOR_MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    except ValueError:
        print(json.dumps({"status": "invalid_private_configuration"}, sort_keys=True))
        return 2
    try:
        import mlflow  # optional dependency, only in execute mode

        publish(mlflow, uri, args.sha, args.pr, counts)
    except Exception:
        print(
            json.dumps(
                {"status": "telemetry_unavailable", "quality_gate": "not_evaluated"},
                sort_keys=True,
            )
        )
        return 0
    print(json.dumps({**result, "status": "recorded"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
