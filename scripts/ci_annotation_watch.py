"""Alert on GitHub check-run annotations even when workflow conclusion is success.

Trusted main checkout only. Never executes PR code, retrieves raw logs or
publishes annotation text; only a closed taxonomy is sent to GitHub Issues.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

WORKFLOWS = {
    "Full regression", "Dependency security audit", "Studio browser journeys",
    "Automated PR risk review", "Automated CI triage and release evidence",
    "Private PC delivery", "Chat approved PC delivery", "CI supply-chain guardrails",
}
CHECK = re.compile(r"^https://api\.github\.com/repos/([^/]+/[^/]+)/check-runs/([0-9]+)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def api(method, path, token, payload=None):
    request = Request(
        "https://api.github.com" + path, method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def trusted(run, repo):
    return (
        isinstance(run, dict) and run.get("name") in WORKFLOWS
        and run.get("status") == "completed"
        and isinstance(run.get("id"), int) and run["id"] > 0
        and isinstance(run.get("head_sha"), str)
        and SHA.fullmatch(run["head_sha"]) is not None
        and (run.get("head_repository") or {}).get("full_name") == repo
    )


def classify(message):
    words = str(message).lower()
    if "node.js 20" in words or "node20" in words:
        return "deprecated_node20"
    if "ubuntu-latest" in words or ("ubuntu" in words and "migrat" in words):
        return "runner_image_change"
    if "deprecat" in words or "obsol" in words:
        return "deprecated_component"
    if "vulnerab" in words or "cve-" in words or "security" in words:
        return "security_warning"
    return "other_annotation"


def summarize(items):
    result = Counter()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid annotation")
        severity = item.get("annotation_level")
        category = classify(str(item.get("title") or "") + " " + str(item.get("message") or ""))
        if severity in ("warning", "failure") or (severity == "notice" and category != "other_annotation"):
            result[(severity, category)] += 1
    return result


def collect(run, repo, token):
    data = api("GET", f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100", token)
    jobs = data.get("jobs")
    if (not isinstance(jobs, list) or data.get("total_count") != len(jobs)
            or len(jobs) > 100):
        raise ValueError("incomplete workflow job list")
    counts = Counter()
    for job in jobs:
        match = CHECK.fullmatch(str(job.get("check_run_url", "")))
        if not match or match.group(1).lower() != repo.lower():
            raise ValueError("missing/foreign check-run id")
        check_id = int(match.group(2))
        for page in range(1, 5):
            items = api("GET", f"/repos/{repo}/check-runs/{check_id}/annotations?per_page=100&page={page}", token)
            if not isinstance(items, list) or (page == 4 and items):
                raise ValueError("incomplete check-run annotations")
            counts.update(summarize(items))
            if len(items) < 100:
                break
    return counts


def marker(run_id):
    return "<!-- arvor-ci-warning:" + str(run_id) + " -->"


def existing_issue(repo, run_id, token):
    for page in range(1, 11):
        items = api("GET", f"/repos/{repo}/issues?state=all&per_page=100&page={page}", token)
        if not isinstance(items, list):
            raise ValueError("incomplete issue listing")
        for item in items:
            if "pull_request" not in item and marker(run_id) in (item.get("body") or ""):
                return item
        if len(items) < 100:
            return None
    raise ValueError("too many issues for safe deduplication")


def body(run, repo, counts):
    lines = [
        marker(run["id"]),
        "## Alerte GitHub CI (un workflow vert peut contenir des avertissements)",
        "- Workflow : " + run["name"],
        "- SHA : " + run["head_sha"],
        "- Conclusion : " + str(run.get("conclusion") or "unknown"),
        "- Exécution : https://github.com/" + repo + "/actions/runs/" + str(run["id"]),
        "- Catégories normalisées (aucun log ni message brut) :",
    ]
    lines += ["  - " + level + " / " + tag + " : " + str(n)
              for (level, tag), n in sorted(counts.items())]
    lines += [
        "", "Examiner les annotations dans Actions, corriger via PR, tester.",
        "Avertissement != vulnérabilité avérée. Aucun accord MEP implicite.",
    ]
    return "\n".join(lines) + "\n"


def monitor(run, repo, token):
    if not trusted(run, repo):
        return "Ignored unrelated or untrusted run"
    counts = collect(run, repo, token)
    if not counts:
        return "No warning/failure annotations for run " + str(run["id"])
    previous = existing_issue(repo, run["id"], token)
    payload = body(run, repo, counts)
    if previous:
        if previous.get("body") != payload or previous.get("state") != "open":
            api("PATCH", f"/repos/{repo}/issues/{previous['number']}", token,
                {"body": payload, "state": "open"})
        return "Deduplicated CI issue #" + str(previous["number"])
    issue = api("POST", f"/repos/{repo}/issues", token, {
        "title": "[CI WARNING] " + run["name"] + " - run " + str(run["id"]),
        "body": payload,
    })
    return "Created CI issue #" + str(issue["number"])


def recent(repo, token):
    result = api("GET", f"/repos/{repo}/actions/runs?per_page=100", token)
    if not isinstance(result.get("workflow_runs"), list):
        raise ValueError("invalid run listing")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    for run in result["workflow_runs"]:
        try:
            date = datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if date >= cutoff and trusted(run, repo):
            yield run


def main():
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    if not REPO.fullmatch(repo):
        raise ValueError("invalid repo")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    kind = os.environ.get("GITHUB_EVENT_NAME", "")
    if kind == "workflow_run":
        runs = [event.get("workflow_run") or {}]
    elif kind in ("schedule", "workflow_dispatch"):
        runs = list(recent(repo, token))
    else:
        raise ValueError("unsupported trigger")
    results = [monitor(run, repo, token) for run in runs]
    output = "\n".join(results) if results else "No recently completed CI runs."
    print(output)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write("## CI annotation watch\n\n" + output + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError):
        print("::error::CI warning supervision unavailable: inspect permissions and API")
        sys.exit(1)
