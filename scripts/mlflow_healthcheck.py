"""Read-only MLflow health check for the private Arvor server.

Exit codes: 0 healthy, 1 unavailable, 2 invalid configuration.
No secret is ever printed; only booleans, counts and durations.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.observability.mlflow_tracker import TrackerConfigurationError, configured_uri


def load_env_file(path):
    """Minimal KEY=VALUE loader; never expands or executes anything."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.isidentifier():
            values[key] = value
    return values


def health(uri, timeout):
    request = urllib.request.Request(uri + "/health", method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(64)
        return response.status == 200 and body.strip().upper() == b"OK"


def wait_ready(uri, seconds, timeout):
    deadline = time.monotonic() + seconds
    while True:
        try:
            if health(uri, timeout):
                return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--wait", type=float, default=0.0, help="Seconds to wait for /health")
    parser.add_argument("--full", action="store_true", help="Artifact round-trip through MinIO")
    parser.add_argument("--replay", action="store_true",
                        help="Replay the bounded local spool once (idempotent)")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    if args.env_file:
        try:
            from infrastructure.observability.mlflow_env import (
                ClientEnvironmentError, load_client_environment)
            load_client_environment(args.env_file)
        except ClientEnvironmentError as error:
            print(json.dumps({"healthy": False, "error": error.code}))
            return 2
        except (OSError, ImportError):
            print(json.dumps({"healthy": False, "error": "env_file_unreadable"}))
            return 2
    uri = os.getenv("MLFLOW_TRACKING_URI", "")
    try:
        uri = configured_uri(uri)
    except TrackerConfigurationError:
        print(json.dumps({"healthy": False, "error": "tracking_uri_invalid"}))
        return 2
    started = time.monotonic()
    if not wait_ready(uri, max(0.0, args.wait), args.timeout):
        print(json.dumps({"healthy": False, "error": "health_unavailable", "uri": uri}))
        return 1
    result = {"healthy": True, "uri": uri,
              "health_seconds": round(time.monotonic() - started, 3)}
    try:
        import mlflow
    except ImportError:
        print(json.dumps({**result, "healthy": False, "error": "mlflow_missing"}))
        return 2
    try:
        mlflow.set_tracking_uri(uri)
        client = mlflow.MlflowClient()
        experiments = client.search_experiments(max_results=200)
        result["experiments"] = len(experiments)
        if args.replay:
            from infrastructure.observability.mlflow_tracker import flush_spool
            result["replay"] = flush_spool()
        if args.full:
            name = "arvor-health"
            experiment = client.get_experiment_by_name(name)
            experiment_id = (client.create_experiment(name) if experiment is None
                             else experiment.experiment_id)
            payload = ("arvor-health-" + uuid.uuid4().hex).encode("utf-8")
            run = client.create_run(experiment_id, run_name="healthcheck")
            try:
                payload = "arvor-health-" + uuid.uuid4().hex
                client.log_text(run.info.run_id, payload, "probe.txt")
                local = client.download_artifacts(run.info.run_id, "probe.txt")
                downloaded = Path(local).read_text(encoding="utf-8")
                result["artifact_roundtrip"] = downloaded == payload
                if not result["artifact_roundtrip"]:
                    result["healthy"] = False
                    result["error"] = "artifact_mismatch"
            finally:
                client.delete_run(run.info.run_id)
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        print(json.dumps(result))
        return 0 if result["healthy"] else 1
    except Exception as error:  # noqa: BLE001 - report a category, never a secret
        print(json.dumps({**result, "healthy": False,
                          "error": "tracking_unavailable",
                          "detail": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
