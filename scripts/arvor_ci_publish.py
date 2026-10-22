"""Trusted external GitHub status + Slack publisher; opt-in only. No merge or deployment."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from uuid import UUID

from scripts.arvor_ci_attestation import verify

REPO = "richardyoann/saas-directeur-editorial"
CONTEXT = "arvor/local-ci-attested"


def http_json(method, url, token=None, payload=None):
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


def fresh_receipt(receipt, now=None):
    now = now or datetime.now(timezone.utc)
    started = datetime.fromisoformat(receipt["started_at"])
    finished = datetime.fromisoformat(receipt["finished_at"])
    if started > now + timedelta(minutes=2) or finished > now + timedelta(minutes=2) or now - finished > timedelta(hours=2):
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


def prepare(envelope, key, key_id, *, now=None):
    evidence = verify(envelope, key, key_id)
    fresh_receipt(evidence, now)
    state = "success" if evidence["status"] == "success" else "failure"
    return evidence, state


def publish(envelope, key, key_id, token, slack_url, sent_dir, *, request=http_json):
    receipt, state = prepare(envelope, key, key_id)
    if not token:
        raise ValueError("Missing GitHub publisher token")
    if os.environ.get("ARVOR_LOCAL_CI_FULL_PARITY_APPROVED") != "true":
        raise ValueError("Local CI parity and supervisor are not yet approved")
    if slack_url and not slack_url.startswith("https://hooks.slack.com/"):
        raise ValueError("Slack webhook host is not allowed")
    sent_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    sent_dir.chmod(0o700)
    UUID(receipt["run_id"])
    marker = sent_dir / (receipt["run_id"] + ".sent")
    if marker.exists():
        raise ValueError("Run has already been published")
    verify_remote(receipt, token, request)
    description = "Local CI evidence: " + state + "; human review still required"
    url = "https://github.com/" + REPO + "/pull/" + str(receipt["pr"])
    response = request("POST", "https://api.github.com/repos/" + REPO + "/statuses/" + receipt["sha"], token,
                       {"state": state, "context": CONTEXT, "description": description, "target_url": url})
    if response.get("state") != state:
        raise ValueError("GitHub status publication not acknowledged")
    marker.write_text(state + "\n", encoding="utf-8")
    marker.chmod(0o600)
    if slack_url:
        message = ("Arvor CI locale " + ("OK" if state == "success" else "KO") +
                   " | PR #" + str(receipt["pr"]) + " | SHA " + receipt["sha"] +
                   " | Gates " + str(sum(bool(g["passed"]) for g in receipt["gates"])) + "/" +
                   str(len(receipt["gates"])) + " | Revue humaine obligatoire | " + url)
        request("POST", slack_url, None, {"text": message, "unfurl_links": False})
    return state


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--attestation", required=True, type=Path)
    p.add_argument("--public-key", required=True, type=Path)
    p.add_argument("--key-id", required=True)
    p.add_argument("--sent-dir", type=Path, default=Path.home() / ".local/state/arvor-local-ci")
    p.add_argument("--publish", action="store_true", help="External network write, explicitly opt-in")
    a = p.parse_args()
    try:
        evidence = json.loads(a.attestation.read_text(encoding="utf-8"))
        public = a.public_key.read_bytes()
        receipt, state = prepare(evidence, public, a.key_id)
        if not a.publish:
            print(json.dumps({"mode": "dry-run", "status": state, "sha": receipt["sha"]}))
            return 0 if state == "success" else 1
        state = publish(evidence, public, a.key_id, os.environ.get("ARVOR_GITHUB_STATUS_TOKEN"),
                        os.environ.get("ARVOR_SLACK_WEBHOOK_URL"), a.sent_dir)
        print(json.dumps({"mode": "published", "status": state, "sha": receipt["sha"]}))
        return 0 if state == "success" else 1
    except (OSError, ValueError, TypeError, KeyError, TimeoutError) as exc:
        print("Publisher blocked: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
