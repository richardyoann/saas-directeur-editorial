"""OpenCode JSONL telemetry observer; never a CI or merge authority."""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from scripts.poc_mlflow_qwen import private_url

SHA = re.compile(r"[a-fA-F0-9]{40}\Z")
KEYS = ("events_total", "content_events", "tool_events", "error_events", "step_events", "other_events")
MAX_LINE = 1048576
MAX_BYTES = 33554432

def summarize(stream):
    counts = Counter()
    total = 0
    while True:
        line = stream.readline(MAX_LINE + 1)
        if not line:
            break
        total += len(line)
        if len(line) > MAX_LINE or total > MAX_BYTES:
            raise ValueError("stream_limit")
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            raise ValueError("invalid_json") from None
        if not isinstance(event, dict):
            raise ValueError("invalid_shape")
        counts["events_total"] += 1
        if counts["events_total"] > 50000:
            raise ValueError("too_many_events")
        kind = event.get("type")
        if kind in ("text", "reasoning", "message", "message.part.updated"):
            category = "content_events"
        elif isinstance(kind, str) and (kind.startswith("tool.") or kind in ("tool_use", "tool_call", "tool_result", "tool")):
            category = "tool_events"
        elif isinstance(kind, str) and (kind.endswith(".error") or kind == "error"):
            category = "error_events"
        elif isinstance(kind, str) and kind.startswith("step"):
            category = "step_events"
        else:
            category = "other_events"
        counts[category] += 1
    if not counts["events_total"]:
        raise ValueError("empty_stream")
    return {key: counts[key] for key in KEYS}

def publish(mlflow, uri, sha, pr, counts):
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("arvor-opencode-observability-poc")
    with mlflow.start_run(run_name="opencode-jsonl-observation") as run:
        mlflow.log_param("commit_sha", sha.lower())
        if pr:
            mlflow.log_param("pr_number", pr)
        mlflow.set_tag("trust_level", "unverified_observability")
        mlflow.set_tag("merge_or_deploy_authorized", "false")
        for key in KEYS:
            mlflow.log_metric(key, counts[key])
        return run.info.run_id

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--input", default="-")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not SHA.fullmatch(args.sha) or (args.pr is not None and args.pr < 1):
        print('{"status":"invalid_metadata"}')
        return 2
    try:
        if args.input == "-":
            counts = summarize(sys.stdin.buffer)
        else:
            path = Path(args.input)
            if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
                raise ValueError("invalid_input")
            with path.open("rb") as source:
                counts = summarize(source)
    except (OSError, ValueError):
        print('{"status":"invalid_event_stream"}')
        return 2
    result = {"status": "observed_only", "quality_gate": "not_evaluated", **counts}
    if not args.execute:
        print(json.dumps(result, sort_keys=True))
        return 0
    try:
        uri = private_url(os.getenv("ARVOR_MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"), loopback_only=True)
    except ValueError:
        print('{"status":"invalid_private_configuration"}')
        return 2
    try:
        import mlflow
        publish(mlflow, uri, args.sha, args.pr, counts)
    except Exception:
        print('{"status":"telemetry_unavailable","quality_gate":"not_evaluated"}')
        return 0
    print(json.dumps({**result, "status": "recorded"}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
