"""Private WSL/Linux release: test candidate, switch service, rollback on failure.

Requires a preconfigured user service and runner. Never migrates the SaaS DB.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

from live_api_check import check


def assert_current_main(sha):
    token = os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request(
        "https://api.github.com/repos/richardyoann/saas-directeur-editorial/git/ref/heads/main",
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        current_sha = json.load(response)["object"]["sha"]
    if current_sha != sha:
        raise RuntimeError("Superseded release; wait for current main CI")


def command(args, cwd=None, quiet=True):
    subprocess.run(args, cwd=cwd, check=True, timeout=600,
                   stdout=subprocess.DEVNULL if quiet else None,
                   stderr=subprocess.DEVNULL if quiet else None)


def point(current: Path, target: Path):
    temporary = current.with_name(".current-next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, current)


def activate(current: Path, candidate: Path, restart, verify, stop):
    if current.exists() and not current.is_symlink():
        raise ValueError("Current must be a release symlink")
    previous = current.resolve(strict=True) if current.is_symlink() else None
    point(current, candidate)
    try:
        restart()
        verify()
    except Exception:
        if previous is not None:
            point(current, previous)
            restart()
            verify()
        else:
            current.unlink(missing_ok=True)
            stop()
        raise


def wait_api(url, process=None):
    import httpx
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError("Candidate API stopped")
        try:
            with httpx.Client(timeout=1, trust_env=False) as client:
                response = client.get(url + "/health")
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError("API unavailable")


def deploy(source: Path, root: Path, config: Path, sha: str, port: int):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Full immutable commit SHA required")
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid service port")
    if not root.is_absolute() or not config.is_absolute() or not config.is_file():
        raise ValueError("Absolute release root and existing config required")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != sha:
        raise ValueError("Checkout differs from expected SHA")
    command(["git", "diff", "--exit-code", "HEAD"], source)
    assert_current_main(sha)
    command(["systemctl", "--user", "cat", "editorial-api.service"])
    service_directory = subprocess.check_output(["systemctl", "--user", "show",
        "editorial-api.service", "--property=WorkingDirectory", "--value"], text=True).strip()
    if service_directory != str(root / "current"):
        raise ValueError("Service does not use the configured release root")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        releases = root / "releases"
        releases.mkdir(exist_ok=True)
        # A unique directory preserves previous and partially failed releases.
        candidate = releases / (sha + "-" + str(time.time_ns()))
        candidate.mkdir()
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).decode().split("\0")
        for name in filter(None, paths):
            relative = Path(name)
            src = source / relative
            if relative.is_absolute() or ".." in relative.parts or src.is_symlink():
                raise ValueError("Unsafe tracked path")
            dest = candidate / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        command([sys.executable, "-m", "venv", str(candidate / ".venv")])
        python = str(candidate / ".venv/bin/python")
        command([python, "-m", "pip", "install", "-r", "requirements.txt", "psycopg[binary]==3.3.6"], candidate)
        # Historical tests use only the ephemeral DB supplied by the workflow.
        command([python, "scripts/run_regression.py"], candidate, quiet=False)
        (candidate / ".env").symlink_to(config)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            candidate_port = sock.getsockname()[1]
        process = subprocess.Popen([python, "-m", "uvicorn", "apps.api.main:app",
            "--host", "127.0.0.1", "--port", str(candidate_port)], cwd=candidate,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            url = f"http://127.0.0.1:{candidate_port}"
            wait_api(url, process)
            check(url)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        url = f"http://127.0.0.1:{port}"
        def verify():
            wait_api(url)
            pid = int(subprocess.check_output(["systemctl", "--user", "show",
                "editorial-api.service", "--property=MainPID", "--value"], text=True).strip())
            if pid <= 0 or Path(f"/proc/{pid}/cwd").resolve(strict=True) != (root / "current").resolve(strict=True):
                raise RuntimeError("Service did not start the selected release")
            check(url)
        assert_current_main(sha)
        activate(root / "current", candidate,
            lambda: command(["systemctl", "--user", "restart", "editorial-api.service"]),
            verify, lambda: command(["systemctl", "--user", "stop", "editorial-api.service"]))
        report = {"sha": sha, "regression": "passed", "candidate_live": "passed",
                  "installed_live": "passed", "database_migration": "none"}
        (root / "last_delivery.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        deploy(Path.cwd(), args.root, args.config, args.sha, args.port)
    except Exception as error:
        print(json.dumps({"delivery": "blocked", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
