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
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4, uuid5

from dotenv import dotenv_values
# Support both direct CLI invocation and import as scripts.deploy_local in tests.
if __package__:
    from .live_api_check import check
else:
    from live_api_check import check

# Running scripts/deploy_local.py directly otherwise imports only scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editorial.runtime_secrets import secret_from_sources


def deployment_secret(name, settings):
    """Resolve env or absolute file path without exposing credentials to logs."""
    values = dict(settings)
    for key in (name, name + "_FILE", "CREDENTIALS_DIRECTORY"):
        if key in os.environ and os.environ[key]:
            values[key] = os.environ[key]
    return secret_from_sources(name, values)



def assert_current_main(sha):
    token = os.environ["GITHUB_TOKEN"]
    request = urllib.request.Request(
        "https://api.github.com/repos/richardyoann/saas-directeur-editorial/git/ref/heads/main",
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        current_sha = json.load(response)["object"]["sha"]
    if current_sha != sha:
        raise RuntimeError("Superseded release; wait for current main CI")


def assert_ci_success(sha):
    """Refuse an untested SHA even for a manual GitHub dispatch."""
    token = os.environ["GITHUB_TOKEN"]
    for workflow in ("regression.yml", "security-deps.yml",
                     "ci-policy.yml", "secret-scan.yml"):
        query = urlencode({"head_sha": sha, "branch": "main", "event": "push",
                           "status": "success", "per_page": 15})
        request = urllib.request.Request(
            "https://api.github.com/repos/richardyoann/saas-directeur-editorial/"
            f"actions/workflows/{workflow}/runs?{query}",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
        runs = data.get("workflow_runs", [])
        if not any(run.get("head_sha") == sha
                   and run.get("head_branch") == "main"
                   and run.get("event") == "push"
                   and run.get("status") == "completed"
                   and run.get("conclusion") == "success" for run in runs):
            raise RuntimeError("Required CI evidence missing for approved SHA")


def verify_approved_sha(sha):
    """Approval must be a separate repo variable, never an API response or PR."""
    approved = os.environ.get("LOCAL_PC_APPROVED_SHA", "")
    if (not re.fullmatch(r"[0-9a-f]{40}", sha)
            or os.environ.get("LOCAL_PC_ENABLED") != "true" or approved != sha):
        raise RuntimeError("Exact SHA approval missing")


def disposable_database_url(url, business_url):
    """Validate dedicated disposable PostgreSQL target before ANY test writes."""
    if not isinstance(url, str) or not isinstance(business_url, str) or not business_url:
        raise ValueError("Both test and private business database URLs are required")
    parsed = urlsplit(url)
    if (parsed.scheme not in {"postgresql", "postgres"}
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username != "po_test" or parsed.password != "ephemeral_ci_only"
            or parsed.path != "/po_test" or parsed.query or parsed.fragment
            or parsed.port is None or url == business_url):
        raise ValueError("Refusing non-disposable PostgreSQL test target")
    # Distinct database identity, not merely URL-string inequality.
    production = urlsplit(business_url)
    if (production.scheme in {"postgresql", "postgres"}
            and production.hostname in {parsed.hostname, "localhost", "127.0.0.1"}
            and production.port == parsed.port
            and production.path == parsed.path):
        raise ValueError("Business and test database share an identity")
    return url


def candidate_test_environment(test_url, settings):
    """Force isolated database + actor, even if runner exports production vars."""
    business_url = deployment_secret("PO_DATABASE_URL", settings)
    disposable_database_url(test_url, business_url)
    environment = os.environ.copy()
    environment.update(PO_DATABASE_URL=test_url, PO_DATABASE_URL_FILE="",
                       EDITORIAL_TENANT_ID=str(uuid4()), EDITORIAL_TENANT_ID_FILE="",
                       EDITORIAL_ACTOR_ID=str(uuid4()), EDITORIAL_ACTOR_ID_FILE="",
                       EDITORIAL_ASYNC_ENABLED="false")
    return environment


def prepare_disposable_editorial_db(url, business_url):
    """Only the dedicated CI PostgreSQL container may receive schema migrations."""
    disposable_database_url(url, business_url)
    import psycopg
    migration = Path(__file__).resolve().parents[1] / "pilotage/migration.sql"
    with psycopg.connect(url, connect_timeout=5) as conn:
        conn.execute(migration.read_text())


def check_readonly_editorial(url, token):
    """Verify the private DB read path without generating or writing runs."""
    import httpx
    if not isinstance(token, str) or len(token) < 32:
        raise RuntimeError("Editorial auth unavailable")
    with httpx.Client(timeout=10, trust_env=False) as client:
        endpoint = url + "/editorial/runs?limit=1"
        denied = client.get(endpoint)
        if denied.status_code != 401:
            raise RuntimeError("Unauthenticated editorial listing accepted")
        response = client.get(endpoint, headers={"Authorization": "Bearer " + token})
        if response.status_code != 200 or not isinstance(response.json().get("runs"), list):
            raise RuntimeError("Read-only editorial listing unavailable")


def assert_service_release(expected: Path, proc_root: Path = Path("/proc")):
    """Bind HTTP evidence to the actual systemd process working directory."""
    pid = subprocess.check_output([
        "systemctl", "--user", "show", "editorial-api.service",
        "--property=MainPID", "--value"], text=True).strip()
    if not pid.isdecimal() or int(pid) <= 0:
        raise RuntimeError("Installed service has no live process")
    try:
        actual = (proc_root / pid / "cwd").resolve(strict=True)
        target = expected.resolve(strict=True)
    except OSError:
        raise RuntimeError("Cannot verify installed release") from None
    if actual != target:
        raise RuntimeError("Service runs a different release")


def already_delivered(root: Path, sha: str) -> bool:
    report_path = root / "last_delivery.json"
    current = root / "current"
    if not report_path.is_file() or not current.is_symlink():
        return False
    try:
        report = json.loads(report_path.read_text())
        release = current.resolve(strict=True)
    except (OSError, ValueError):
        return False
    return (report.get("sha") == sha and report.get("installed_live") == "passed"
            and release.parent == (root / "releases").resolve()
            and release.name.startswith(sha + "-"))


def command(args, cwd=None, quiet=True, env=None):
    subprocess.run(args, cwd=cwd, check=True, timeout=600, env=env,
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


def check_runtime_readonly(url):
    """Only GET probes in the active application; never creates a user run."""
    import httpx
    with httpx.Client(timeout=5, trust_env=False) as client:
        health = client.get(url + "/health")
        if health.status_code != 200 or health.json().get("status") != "ok":
            raise RuntimeError("Activated API health unavailable")
        ready = client.get(url + "/ready")
        if ready.status_code != 200 or ready.json().get("ready") is not True:
            raise RuntimeError("Activated API dependencies unavailable")


def check_studio(url: str, web_password: str):
    """Verify the real private UI/session/list/logout path before switching releases.

    Never log the password, session cookie, CSRF token or user data.
    """
    import httpx

    if not isinstance(web_password, str) or len(web_password) < 32:
        raise RuntimeError("Private Studio password missing")
    origin = {"Origin": url}
    with httpx.Client(timeout=10, trust_env=False) as client:
        page = client.get(url + "/studio")
        if page.status_code != 200 or "text/html" not in page.headers.get("content-type", ""):
            raise RuntimeError("Studio HTML unavailable")
        for filename in ("studio.css", "studio.js"):
            asset = client.get(url + "/studio/assets/" + filename)
            if asset.status_code != 200:
                raise RuntimeError("Studio asset unavailable")
        session = client.get(url + "/studio/session")
        if session.status_code != 200 or session.json().get("authenticated") is not False:
            raise RuntimeError("Studio session not initially anonymous")
        login = client.post(url + "/studio/session", json={"password": web_password}, headers=origin)
        if login.status_code != 200:
            raise RuntimeError("Studio login failed")
        body = login.json()
        csrf = body.get("csrf")
        cookie = login.headers.get("set-cookie", "").lower()
        if (body.get("authenticated") is not True or not isinstance(csrf, str)
                or len(csrf) < 32 or "httponly" not in cookie or "samesite=strict" not in cookie):
            raise RuntimeError("Studio session contract invalid")
        index = client.get(url + "/studio/api/runs?limit=1")
        if index.status_code != 200 or not isinstance(index.json().get("runs"), list):
            raise RuntimeError("Studio authenticated listing unavailable")
        logout = client.post(url + "/studio/logout", headers=origin | {"X-CSRF-Token": csrf})
        if logout.status_code != 200:
            raise RuntimeError("Studio logout failed")
        after = client.get(url + "/studio/session")
        if after.status_code != 200 or after.json().get("authenticated") is not False:
            raise RuntimeError("Studio logout did not invalidate session")


def deploy(source: Path, root: Path, config: Path, sha: str, port: int):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Full immutable commit SHA required")
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid service port")
    if not root.is_absolute() or not config.is_absolute() or not config.is_file():
        raise ValueError("Absolute release root and existing config required")
    settings = dotenv_values(config)
    editorial_token = deployment_secret("EDITORIAL_API_TOKEN", settings)
    if not isinstance(editorial_token, str) or len(editorial_token) < 32:
        raise ValueError("Editorial authentication missing from private configuration")
    web_password = deployment_secret("EDITORIAL_WEB_PASSWORD", settings)
    if (not isinstance(web_password, str) or len(web_password) < 32
            or web_password == editorial_token):
        raise ValueError("Distinct private Studio password is required")
    business_key = uuid5(UUID("4b0d4554-36f5-4aeb-bbc2-8d811535f699"), sha)
    test_url = os.environ.get("PO_TEST_DATABASE_URL", "")
    candidate_env = candidate_test_environment(test_url, settings)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != sha:
        raise ValueError("Checkout differs from expected SHA")
    command(["git", "diff", "--exit-code", "HEAD"], source)
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=source, text=True).strip():
        raise ValueError("Tracked checkout modifications invalidate SHA evidence")
    verify_approved_sha(sha)
    assert_current_main(sha)
    assert_ci_success(sha)
    command(["systemctl", "--user", "cat", "editorial-api.service"])
    service_directory = subprocess.check_output(["systemctl", "--user", "show",
        "editorial-api.service", "--property=WorkingDirectory", "--value"], text=True).strip()
    if service_directory != str(root / "current"):
        raise ValueError("Service does not use the configured release root")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if already_delivered(root, sha):
            assert_service_release(root / "current")
            check_runtime_readonly(f"http://127.0.0.1:{port}")
            check_readonly_editorial(f"http://127.0.0.1:{port}", editorial_token)
            check_studio(f"http://127.0.0.1:{port}", web_password)
            print(json.dumps({"sha": sha, "delivery": "already_verified"}))
            return
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
        command([python, "scripts/run_regression.py"], candidate, quiet=False, env=candidate_env)
        prepare_disposable_editorial_db(test_url, deployment_secret("PO_DATABASE_URL", settings))
        (candidate / ".env").symlink_to(config)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            candidate_port = sock.getsockname()[1]
        process = subprocess.Popen([python, "-m", "uvicorn", "apps.api.main:app",
            "--host", "127.0.0.1", "--port", str(candidate_port)], cwd=candidate,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=candidate_env)
        try:
            url = f"http://127.0.0.1:{candidate_port}"
            wait_api(url, process)
            check(url, editorial_token=editorial_token, idempotency_key=business_key)
            check_studio(url, web_password)
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
            check_runtime_readonly(url)
            check_readonly_editorial(url, editorial_token)
            check_studio(url, web_password)
        verify_approved_sha(sha)
        assert_current_main(sha)
        assert_ci_success(sha)
        activate(root / "current", candidate,
            lambda: command(["systemctl", "--user", "restart", "editorial-api.service"]),
            verify, lambda: command(["systemctl", "--user", "stop", "editorial-api.service"]))
        report = {"sha": sha, "regression": "passed", "candidate_live": "passed",
                  "installed_live": "passed", "real_editorial_workflow": "passed",
                  "database_migration": "test_database_only",
                  "production_editorial_probe": "read_only",
                  "candidate_editorial_probe": "isolated_test_database"}
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
        raise SystemExit(1) from None
