"""Unattended Arvor PR CI poller. Never merge, push, or deploy."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

REPO = "richardyoann/saas-directeur-editorial"
SHA = re.compile(r"[0-9a-f]{40}\Z")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")
REMOTES = {f"https://github.com/{REPO}", f"https://github.com/{REPO}.git",
           f"git@github.com:{REPO}", f"git@github.com:{REPO}.git"}


def api(url, token, payload=None):
    if not url.startswith(f"https://api.github.com/repos/{REPO}/") and url != "https://slack.com/api/chat.postMessage":
        raise ValueError("unapproved endpoint")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    with urlopen(Request(url, data=data, method="POST" if data is not None else "GET",
                         headers=headers), timeout=20) as response:
        return json.load(response)


def eligible(pr):
    if not isinstance(pr, dict) or pr.get("state") != "open":
        return False
    head, base = pr.get("head") or {}, pr.get("base") or {}
    name = head.get("ref")
    return (isinstance(pr.get("number"), int) and pr["number"] > 0
            and isinstance(name, str) and BRANCH.fullmatch(name) is not None
            and ".." not in name and "//" not in name
            and (head.get("repo") or {}).get("full_name") == REPO
            and base.get("ref") == "main"
            and isinstance(head.get("sha"), str) and SHA.fullmatch(head["sha"]) is not None
            and isinstance(base.get("sha"), str) and SHA.fullmatch(base["sha"]) is not None)


def discover(token):
    found = []
    for page in range(1, 6):
        batch = api(f"https://api.github.com/repos/{REPO}/pulls?state=open&base=main&per_page=100&page={page}", token)
        if not isinstance(batch, list):
            raise RuntimeError("invalid PR list")
        found.extend(p for p in batch if eligible(p))
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("too many PRs; manual review required")
    return sorted(found, key=lambda p: (p.get("updated_at") or "", p["number"]), reverse=True)


def git(root, *args, timeout=120):
    result = subprocess.run(["git", "-C", str(root), *args], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False,
                            env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
    if result.returncode:
        raise RuntimeError("Git command unavailable or refused")
    return result.stdout.strip()


def validate_controller(root, approved_sha):
    if not isinstance(approved_sha, str) or not SHA.fullmatch(approved_sha):
        raise ValueError("exact reviewed controller SHA required")
    if git(root, "rev-parse", "HEAD") != approved_sha or git(root, "status", "--porcelain"):
        raise RuntimeError("unreviewed or dirty CI controller")
    if git(root, "remote", "get-url", "origin") not in REMOTES:
        raise RuntimeError("unapproved Git remote")
    if not (root / "ops/ci/run_and_report.sh").is_file():
        raise RuntimeError("trusted runner missing")


def confirmed_shas(root, pr):
    branch = pr["head"]["ref"]
    git(root, "fetch", "--no-tags", "origin",
        "+refs/heads/main:refs/remotes/origin/main",
        "+refs/heads/" + branch + ":refs/remotes/origin/" + branch)
    base = git(root, "rev-parse", "refs/remotes/origin/main")
    sha = git(root, "rev-parse", "refs/remotes/origin/" + branch)
    if (sha, base) != (pr["head"]["sha"], pr["base"]["sha"]):
        raise RuntimeError("PR moved while being checked")
    ancestor = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", base, sha],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=30, check=False)
    if ancestor.returncode:
        raise RuntimeError("PR must be reconciled with main")
    return sha, base


def state_path(folder, number):
    return folder / ("pr-" + str(number) + ".json")


def should_run(pr, folder, now, force=False):
    if force:
        return True
    try:
        record = json.loads(state_path(folder, pr["number"]).read_text(encoding="utf-8"))
        if (record["sha"], record["base_sha"]) != (pr["head"]["sha"], pr["base"]["sha"]):
            return True
        return datetime.fromisoformat(record["next_run"]) <= now
    except (OSError, ValueError, KeyError, TypeError):
        return True


def record_outcome(folder, pr, result, now):
    hours = 2 if result == "unavailable" else 24
    data = {"number": pr["number"], "sha": pr["head"]["sha"],
            "base_sha": pr["base"]["sha"], "result": result,
            "finished": now.isoformat(), "next_run": (now + timedelta(hours=hours)).isoformat()}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder,
                                     prefix="state-", delete=False) as handle:
        json.dump(data, handle, sort_keys=True)
        handle.write("\n")
        pending = handle.name
    os.chmod(pending, 0o600)
    os.replace(pending, state_path(folder, pr["number"]))


def slack_failure(pr, reason, token, channel):
    message = (f"Arvor CI locale - ATTENTION: controles indisponibles\n"
               f"PR #{pr['number']} / SHA {pr['head']['sha']}\n"
               f"Cause: {reason}\nPas de CI verte, fusion ou livraison PC.")
    ack = api("https://slack.com/api/chat.postMessage", token,
              {"channel": channel, "text": message, "unfurl_links": False, "unfurl_media": False})
    if ack.get("ok") is not True:
        raise RuntimeError("Slack notification unacknowledged")


def configured_tokens():
    directory = os.getenv("CREDENTIALS_DIRECTORY", "")
    if directory:
        credentials = Path(directory).resolve(strict=True)
        return ((credentials / "github_token").read_text(encoding="utf-8").strip(),
                (credentials / "slack_token").read_text(encoding="utf-8").strip())
    return os.environ["ARVOR_CI_GITHUB_TOKEN"], os.environ["ARVOR_CI_SLACK_TOKEN"]


def run_pr(root, folder, pr, github_token, slack_token, channel):
    try:
        sha, base = confirmed_shas(root, pr)
        with tempfile.TemporaryDirectory(prefix="pr-qa-", dir=folder) as workspace:
            checkout = Path(workspace) / "checkout"
            git(root, "worktree", "add", "--detach", str(checkout), sha)
            try:
                env = {**os.environ, "ARVOR_CI_GITHUB_TOKEN": github_token,
                       "ARVOR_CI_SLACK_TOKEN": slack_token, "ARVOR_CI_SLACK_CHANNEL": channel}
                if os.getenv("CREDENTIALS_DIRECTORY"):
                    env["ARVOR_CI_HMAC_KEY_FILE"] = str(Path(os.environ["CREDENTIALS_DIRECTORY"]) / "hmac_key")
                outcome = subprocess.run(["bash", str(root / "ops/ci/run_and_report.sh"),
                                          str(checkout), sha, base, str(pr["number"])],
                                         cwd=root, env=env, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, timeout=10800, check=False)
                result = "passed" if outcome.returncode == 0 else "failed" if outcome.returncode == 1 else "unavailable"
            finally:
                git(root, "worktree", "remove", "--force", str(checkout))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        result = "unavailable"
    if result == "unavailable":
        slack_failure(pr, "preflight_or_publisher_unavailable", slack_token, channel)
    record_outcome(folder, pr, result, datetime.now(timezone.utc))
    return result


def cycle(root, state_dir, controller_sha, github_token, slack_token, channel,
          *, limit=1, only_pr=None, force=False):
    if limit < 1 or limit > 4:
        raise ValueError("max PRs per tick: 1..4")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    with (state_dir / "watch.lock").open("a+") as lock:
        os.chmod(state_dir / "watch.lock", 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        validate_controller(root, controller_sha)
        now = datetime.now(timezone.utc)
        selected = (p for p in discover(github_token)
                    if (only_pr is None or p["number"] == only_pr)
                    and should_run(p, state_dir, now, force=force))
        return [(p["number"], run_pr(root, state_dir, p, github_token, slack_token, channel))
                for p in list(selected)[:limit]]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/state/arvor-ci/watch")
    parser.add_argument("--max-prs", type=int, default=1)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.force and not args.pr:
        parser.error("--force requires one --pr number")
    try:
        github, slack = configured_tokens()
        if not github or not slack:
            raise ValueError("credentials unavailable")
        completed = cycle(args.controller.resolve(strict=True), args.state,
                          os.environ["ARVOR_CI_CONTROLLER_SHA"], github, slack,
                          os.environ["ARVOR_CI_SLACK_CHANNEL"], limit=args.max_prs,
                          only_pr=args.pr, force=args.force)
        for number, verdict in completed:
            print(f"PR #{number}: {verdict}; no merge or deployment")
        return 0 if all(verdict == "passed" for _, verdict in completed) else 1
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print("Arvor autopilot unavailable: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
