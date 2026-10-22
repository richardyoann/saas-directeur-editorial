"""Trusted publisher for SHA-bound local CI reports; NEVER merges or deploys.

Keep GITHUB_TOKEN, SLACK_BOT_TOKEN and the signing key outside CI test containers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

try:
    from scripts.arvor_ci_evidence import canonical, key_bytes, seal, verify
except ModuleNotFoundError:
    from arvor_ci_evidence import canonical, key_bytes, seal, verify

REPO = "richardyoann/saas-directeur-editorial"


def request_json(url, token, *, payload=None):
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    data = canonical(payload) if payload is not None else None
    with urlopen(Request(url, data=data, method="POST" if payload is not None else "GET", headers=headers), timeout=15) as resp:
        return json.load(resp)


def store_sealed(report_path, output, sha, key_path):
    if output.exists() or output.is_symlink():
        raise FileExistsError("refuse overwrite sealed evidence")
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    envelope = seal(raw, sha, key_bytes(key_path))
    with output.open("x", encoding="utf-8") as fh:
        json.dump(envelope, fh, sort_keys=True)
        fh.write("\n")
    output.chmod(0o600)
    return envelope


def summary(envelope):
    report = envelope["report"]
    gates = report["gates"]
    ok = sum(g["status"] == "passed" for g in gates.values())
    failed = ", ".join(name for name, gate in gates.items() if gate["status"] != "passed") or "aucun"
    return f"{ok}/{len(gates)} contrôles OK ; KO/bloqués : {failed} ; tests ignorés : {sum(g['skipped'] for g in gates.values())}"


def publish(envelope, sha, key, pr_number, github_token, slack_token, slack_channel):
    passed = verify(envelope, sha, key)
    if not isinstance(pr_number, int) or pr_number <= 0:
        raise ValueError("invalid PR number")
    if not github_token or not slack_token or not slack_channel:
        raise ValueError("missing GitHub or Slack publisher credentials")
    api = "https://api.github.com/repos/" + REPO
    pr = request_json(api + "/pulls/" + str(pr_number), github_token)
    if (pr.get("state") != "open" or pr.get("head", {}).get("sha") != sha or
        pr.get("base", {}).get("ref") != "main" or
        pr.get("head", {}).get("repo", {}).get("full_name") != REPO):
        raise ValueError("PR stale or wrong base/head; no status published")
    link = f"https://github.com/{REPO}/pull/{pr_number}"
    digest = hashlib.sha256(canonical(envelope)).hexdigest()
    state = "success" if passed else "failure"
    request_json(api + "/statuses/" + sha, github_token, payload={
        "state": state, "context": "arvor/local-ci",
        "description": f"{sum(g['status']=='passed' for g in envelope['report']['gates'].values())}/9 contrôles locaux ; revue humaine requise",
        "target_url": link,
    })
    # Never publish private logs, test DB URLs, tokens, prompts or signing key.
    note = ("Contrôles locaux attestés — PAS une approbation humaine ni une MEP\n"
            f"SHA : `{sha}`\nStatut : **{state}**\n{summary(envelope)}\n"
            f"Empreinte SHA-256 de l'attestation : `{digest}`\n"
            "L'attestation HMAC originale reste privée côté opérateur. Revue humaine obligatoire.")
    request_json(api + "/issues/" + str(pr_number) + "/comments", github_token, payload={"body": note})
    slack = request_json("https://slack.com/api/chat.postMessage", slack_token, payload={
        "channel": slack_channel,
        "text": (f"Arvor CI locale — {'✅ OK' if passed else '❌ KO'}\nPR #{pr_number} · SHA `{sha}`\n"
                 + summary(envelope) + f"\nPreuve SHA-256 : `{digest}`\n{link}\n"
                 "Aucune fusion ni livraison. Revue humaine toujours nécessaire."),
        "unfurl_links": False, "unfurl_media": False,
    })
    if slack.get("ok") is not True:
        raise RuntimeError("Slack refused message (GitHub status may already be published)")
    return state


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    sign = commands.add_parser("seal")
    sign.add_argument("--report", required=True, type=Path)
    sign.add_argument("--output", required=True, type=Path)
    sign.add_argument("--sha", required=True)
    post = commands.add_parser("publish")
    post.add_argument("--proof", required=True, type=Path)
    post.add_argument("--sha", required=True)
    post.add_argument("--pr", required=True, type=int)
    args = parser.parse_args()
    try:
        key_path = os.environ["ARVOR_CI_HMAC_KEY_FILE"]
        key = key_bytes(key_path)
        if args.action == "seal":
            store_sealed(args.report, args.output, args.sha, key_path)
            print("Signed evidence stored privately; no PR merge or deployment")
        else:
            envelope = json.loads(args.proof.read_text(encoding="utf-8"))
            outcome = publish(envelope, args.sha, key, args.pr, os.environ.get("ARVOR_CI_GITHUB_TOKEN", ""),
                              os.environ.get("ARVOR_CI_SLACK_TOKEN", ""), os.environ.get("ARVOR_CI_SLACK_CHANNEL", ""))
            print("GitHub local CI status and Slack: " + outcome)
        return 0
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
        print("CI evidence operation refused/failed; inspect private operator logs", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
