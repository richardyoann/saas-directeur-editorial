"""Trusted external GitHub status + Slack publisher; opt-in only. No merge or deployment."""
import argparse
import fcntl
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from uuid import UUID

from scripts.arvor_ci_attestation import verify
from scripts.arvor_ci_trust import POLICY_VERSION, policy_digest
from scripts.arvor_ci_host_trust import (
    DEFAULT_TRUST_PATH, load_host_trust, verify_host_controller,
    verify_host_key,
)

REPO = "richardyoann/saas-directeur-editorial"


def git(root, *args):
    import subprocess
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   timeout=20).strip()
CONTEXT = "arvor/local-ci-attested"


def http_json(method, url, token=None, payload=None):
    if not url.startswith("https://api.github.com/"):
        raise ValueError("GitHub API URL required")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "arvor-local-ci-publisher/1", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None, method=method, headers=headers)
    with urlopen(request, timeout=12) as response:
        data = response.read()
        if url.startswith("https://hooks.slack.com/"):
            if data.strip() != b"ok":
                raise ValueError("Slack webhook not acknowledged")
            return {"ok": True}
        return json.loads(data)


def fresh_receipt(receipt, provenance, now=None):
    now = now or datetime.now(timezone.utc)
    started = datetime.fromisoformat(receipt["started_at"])
    finished = datetime.fromisoformat(receipt["finished_at"])
    verified = datetime.fromisoformat(provenance["verified_at"])
    if (started > now + timedelta(minutes=2) or finished > now + timedelta(minutes=2)
            or verified > now + timedelta(minutes=2)
            or now - finished > timedelta(hours=2)
            or now - verified > timedelta(hours=2)):
        raise ValueError("Expired or future attestation")


def verify_remote(receipt, token, request=http_json):
    pr = request("GET", "https://api.github.com/repos/" + REPO + "/pulls/" + str(receipt["pr"]), token)
    if (pr.get("state") != "open" or pr.get("merged") is True
            or (pr.get("head") or {}).get("sha") != receipt["sha"]
            or (pr.get("base") or {}).get("sha") != receipt["base_sha"]
            or (pr.get("base") or {}).get("ref") != "main"
            or (pr.get("head") or {}).get("repo", {}).get("full_name") != REPO):
        raise ValueError("PR is no longer the attested revision")
    return pr


def prepare(envelope, key, key_id, *, controller_sha, expected_policy_sha256,
            expected_image_id, now=None):
    evidence = verify(envelope, key, key_id)
    provenance = envelope["provenance"]
    if (provenance["controller_sha"] != controller_sha
            or provenance["policy_version"] != POLICY_VERSION
            or provenance["policy_sha256"] != expected_policy_sha256
            or provenance["image_id"] != expected_image_id
            or provenance["run_id"] != evidence["run_id"]):
        raise ValueError("Attested execution is outside publisher trust policy")
    fresh_receipt(evidence, provenance, now)
    state = "success" if evidence["status"] == "success" else "failure"
    return evidence, state


def publish(envelope, key, key_id, token, slack_url, sent_dir, *,
            controller_sha, expected_policy_sha256, expected_image_id,
            confirm_slack_not_delivered=False, request=http_json):
    receipt, state = prepare(
        envelope, key, key_id, controller_sha=controller_sha,
        expected_policy_sha256=expected_policy_sha256,
        expected_image_id=expected_image_id,
    )
    if not token:
        raise ValueError("Missing GitHub publisher token")
    if slack_url and not slack_url.startswith("https://hooks.slack.com/"):
        raise ValueError("Invalid configured private Slack webhook")
    sent_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sent_dir.is_symlink():
        raise ValueError("Publisher state directory must not be a symlink")
    sent_dir.chmod(0o700)
    UUID(receipt["run_id"])
    github_marker = sent_dir / (receipt["run_id"] + ".github")
    slack_marker = sent_dir / (receipt["run_id"] + ".slack")
    slack_pending = sent_dir / (receipt["run_id"] + ".slack.pending")
    lockfile = sent_dir / (receipt["run_id"] + ".lock")
    # Keep GitHub and Slack acknowledgments independently to permit a Slack
    # retry without publishing a second GitHub status for the same run.
    with lockfile.open("a+", encoding="utf-8") as lock:
        lockfile.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if github_marker.exists() and (not slack_url or slack_marker.exists()):
            raise ValueError("Run has already been published and notified")
        verify_remote(receipt, token, request)
        url = "https://github.com/" + REPO + "/pull/" + str(receipt["pr"])
        status_url = "https://api.github.com/repos/" + REPO + "/statuses/" + receipt["sha"]
        target_url = url + "#arvor-local-ci-run-" + receipt["run_id"]
        if not github_marker.exists():
            # Commit-status POST has no idempotency key. Reconcile its unique
            # target URL before retrying an ambiguous response.
            existing = request("GET", status_url, token)
            if not isinstance(existing, list):
                raise ValueError("GitHub status history unavailable for deduplication")
            matching = [x for x in existing if x.get("context") == CONTEXT
                        and x.get("target_url") == target_url]
            if matching:
                if matching[0].get("state") != state:
                    raise ValueError("Prior GitHub status conflicts with this attestation")
                with github_marker.open("x", encoding="utf-8") as marker:
                    marker.write(state + "\n")
                github_marker.chmod(0o600)
            else:
                verify_remote(receipt, token, request)  # immediately before POST
                response = request("POST", status_url, token,
                                   {"state": state, "context": CONTEXT,
                                    "description": "Local CI " + state + "; human review still required",
                                    "target_url": target_url})
                if response.get("state") != state:
                    raise ValueError("GitHub status publication not acknowledged")
                with github_marker.open("x", encoding="utf-8") as marker:
                    marker.write(state + "\n")
                github_marker.chmod(0o600)
        if slack_url and not slack_marker.exists():
            if slack_pending.exists() and not confirm_slack_not_delivered:
                raise ValueError("Slack delivery outcome is ambiguous; confirm non-delivery before retry")
            if not slack_pending.exists():
                with slack_pending.open("x", encoding="utf-8") as marker:
                    marker.write("delivery attempt started\n")
                    marker.flush()
                    os.fsync(marker.fileno())
                slack_pending.chmod(0o600)
            verify_remote(receipt, token, request)
            message = ("Arvor CI locale " + ("OK" if state == "success" else "KO") +
                       " | run " + receipt["run_id"] + " | PR #" + str(receipt["pr"]) +
                       " | SHA " + receipt["sha"] +
                       " | Gates " + str(sum(bool(g["passed"]) for g in receipt["gates"])) +
                       "/" + str(len(receipt["gates"])) +
                       " | Revue humaine obligatoire | " + url)
            request("POST", slack_url, None, {"text": message, "unfurl_links": False})
            with slack_marker.open("x", encoding="utf-8") as marker:
                marker.write("notified\n")
            slack_marker.chmod(0o600)
            slack_pending.unlink()
    return state


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--attestation", required=True, type=Path)
    p.add_argument("--public-key", required=True, type=Path)
    p.add_argument("--key-id", required=True)
    p.add_argument("--trusted-controller", required=True, type=Path)
    p.add_argument("--controller-sha", required=True)
    p.add_argument("--image-id", required=True)
    p.add_argument("--policy-sha256", required=True)
    p.add_argument("--sent-dir", type=Path, default=Path.home() / ".local/state/arvor-local-ci")
    p.add_argument("--confirm-slack-not-delivered", action="store_true",
                   help="Retry an ambiguous webhook only after independently confirming it was not delivered")
    p.add_argument("--publish", action="store_true", help="External network write, explicitly opt-in")
    a = p.parse_args()
    try:
        host_trust = load_host_trust(DEFAULT_TRUST_PATH)
        if (a.public_key.resolve(strict=True) != Path(host_trust["public_key_path"])
                or a.key_id != host_trust["key_id"]
                or a.controller_sha != host_trust["controller_sha"]
                or a.image_id != host_trust["image_id"]
                or a.policy_sha256 != host_trust["policy_sha256"]
                or a.trusted_controller.resolve(strict=True)
                   != Path(host_trust["controller_path"])
                or a.sent_dir.resolve(strict=False) != Path(host_trust["sent_dir"])):
            raise ValueError("Publisher arguments differ from fixed host trust pins")
        evidence = json.loads(a.attestation.read_text(encoding="utf-8"))
        public = a.public_key.read_bytes()
        trusted = a.trusted_controller.resolve(strict=True)
        verify_host_key(host_trust, public)
        verify_host_controller(host_trust, trusted)
        if (not Path(__file__).resolve().is_relative_to(trusted)
                or git(trusted, "rev-parse", "HEAD") != a.controller_sha
                or git(trusted, "status", "--porcelain")
                or policy_digest(trusted) != a.policy_sha256):
            raise ValueError("Publisher is not running from the pinned clean trust controller")
        receipt, state = prepare(
            evidence, public, a.key_id, controller_sha=a.controller_sha,
            expected_policy_sha256=a.policy_sha256, expected_image_id=a.image_id,
        )
        if not a.publish:
            print(json.dumps({"mode": "dry-run", "status": state, "sha": receipt["sha"]}))
            return 0 if state == "success" else 1
        state = publish(
            evidence, public, a.key_id, os.environ.get("ARVOR_GITHUB_STATUS_TOKEN"),
            os.environ.get("ARVOR_SLACK_WEBHOOK_URL"), a.sent_dir,
            controller_sha=a.controller_sha, expected_policy_sha256=a.policy_sha256,
            expected_image_id=a.image_id,
            confirm_slack_not_delivered=a.confirm_slack_not_delivered,
        )
        print(json.dumps({"mode": "published", "status": state, "sha": receipt["sha"]}))
        return 0 if state == "success" else 1
    except (OSError, ValueError, TypeError, KeyError, TimeoutError) as exc:
        print("Publisher blocked: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
