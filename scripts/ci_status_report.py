"""Safe workflow_run triage: summarize CI and comment actionable failures.

This program MUST run from trusted main, not from pull request code. It never
checks out/evaluates untrusted code and never uses log text as instructions.
Only GitHub job/step statuses are read; no raw logs or secrets published.
"""
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MARKER = "<!-- editorial-ci-triage-v1 -->"
SAFE_RUN_STATES = {"success", "failure", "cancelled", "skipped", "timed_out", "neutral"}
WORKFLOWS = {"Full regression", "Dependency security audit", "Studio browser journeys"}


def api(method, path, token, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request("https://api.github.com" + path, data=body, method=method,
                      headers={"Authorization": "Bearer " + token,
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28",
                               "Content-Type": "application/json"})
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def identify(event, repository):
    run = event.get("workflow_run") or {}
    if (event.get("action") != "completed" or
        run.get("name") not in WORKFLOWS or
        run.get("status") != "completed" or
        (run.get("head_repository") or {}).get("full_name") != repository):
        return None
    run_id, sha = run.get("id"), run.get("head_sha")
    if (not isinstance(run_id, int) or run_id <= 0 or
        not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha)):
        return None
    conclusion = run.get("conclusion")
    if conclusion not in SAFE_RUN_STATES:
        return None
    return run


def classify_failure(jobs, workflow="Full regression"):
    """Conservative reproduction instructions without reading any CI log data."""
    failed_count = sum(job.get("conclusion") in {"failure", "timed_out", "cancelled"}
                       for job in jobs if isinstance(job, dict))
    steps = {
        "Full regression": (
            "Manually reproduce the first failing Python test with "
            "`python scripts/run_regression.py` on an isolated test database; "
            "add a regression test, correct on a dedicated branch and rerun CI."
        ),
        "Dependency security audit": (
            "Manually review `python -m pip_audit -r requirements.txt` "
            "and propose pinned dependency updates in a separate, tested PR."
        ),
        "Studio browser journeys": (
            "Manually reproduce the browser fixture test with "
            "`python -m unittest discover -s browser_checks -v`; "
            "verify that mocked browser tests do not prove the real PC Studio."
        ),
    }
    return {
        "failed_jobs": failed_count,
        "hint": (steps.get(workflow, "Manually inspect the failing GitHub workflow.")
                 + " Do not replay an ambiguous persisted Qwen request."),
    }


def release_packet(run, repository, pc_enabled):
    conclusion = run["conclusion"]
    workflow = run["name"]
    sha = run["head_sha"]
    safe_flag = "off" if pc_enabled == "false" else "on" if pc_enabled == "true" else "unknown"
    lines = [
        "## Private release evidence — not an approval",
        f"- Repository: `{repository}`",
        f"- SHA from completed main CI: `{sha}`",
        f"- Completed workflow: **{workflow}**, conclusion: **{conclusion}**",
        f"- LOCAL_PC_ENABLED at reporting time: **{safe_flag}**",
        "- Deployment: **not performed by this report**",
        "- Human approval: **required for this exact SHA before PC activation**",
        "- Other independent checks (dependency audit / browser) require separate verification.",
        "- Before delivery: verify current main SHA, complete checks, private runner, backup and rollback.",
        "- After delivery: confirm installed SHA, API, Qwen, PostgreSQL, Studio and preserve evidence.",
    ]
    return "\n".join(lines) + "\n"


def triage_comment(run, outcome):
    workflow = run["name"]
    sha = run["head_sha"]
    status = run["conclusion"]
    next_step = ("Latest check passed: the previous CI alert is resolved for this SHA. "
                 "A passing check does not imply code review or PC deployment."
                 if status == "success" else outcome["hint"])
    return ("{marker}\n"
            "### Automated CI triage — {workflow}\n"
            "- Head SHA: `{sha}`\n"
            "- Result: **{status}**\n"
            "- GitHub Actions run ID: `{run_id}`\n"
            "- Failed jobs: **{n}**\n"
            "- Next step: {hint}\n\n"
            "This is a status/heuristic report, not a code review, code fix, deployment approval or verified root cause.\n"
            ).format(marker=MARKER, workflow=workflow, sha=sha, status=status,
                     run_id=run["id"], n=outcome["failed_jobs"], hint=next_step)


def existing_comment(repo, number, token, workflow):
    # Read the bot's own most recent matching marker. Never modify a human comment.
    for page in range(1, 6):
        comments = api("GET", f"/repos/{repo}/issues/{number}/comments?per_page=100&page={page}", token)
        if not isinstance(comments, list):
            return None
        for item in reversed(comments):
            body = item.get("body") or ""
            user = item.get("user") or {}
            if (MARKER in body and f"### Automated CI triage — {workflow}" in body
                    and user.get("type") == "Bot"):
                return item["id"]
        if len(comments) < 100:
            break
    return None


def run_report(event, repository, token, pc_enabled=""):
    run = identify(event, repository)
    if run is None:
        return "Ignored unrelated/untrusted workflow event.\n"
    if run.get("event") == "push" and run.get("head_branch") == "main":
        return release_packet(run, repository, pc_enabled)
    if run.get("event") != "pull_request":
        return "No pull request to triage.\n"

    candidates = run.get("pull_requests") or []
    if len(candidates) != 1:
        return "No unambiguous pull request association; see GitHub Actions run.\n"
    number = candidates[0].get("number")
    if not isinstance(number, int) or number <= 0:
        return "No valid pull request number.\n"
    pr = api("GET", f"/repos/{repository}/pulls/{number}", token)
    if ((pr.get("head") or {}).get("sha") != run["head_sha"] or
            (pr.get("base") or {}).get("ref") != "main" or
            pr.get("state") != "open"):
        return "Stale or closed pull request; no comment written.\n"

    jobs = api("GET", f"/repos/{repository}/actions/runs/{run['id']}/jobs?per_page=100", token)
    if not isinstance(jobs, dict) or jobs.get("total_count", 0) > 100:
        return "Too many jobs or invalid response; manual triage required.\n"
    outcome = classify_failure(jobs.get("jobs") or [], run["name"])
    workflow = run["name"]
    old_id = existing_comment(repository, number, token, workflow)
    if run["conclusion"] == "success" and old_id is None:
        return "CI green; no redundant pull request comment.\n"
    body = triage_comment(run, outcome)
    if old_id is not None:
        api("PATCH", f"/repos/{repository}/issues/comments/{old_id}", token, {"body": body})
        return f"Updated existing PR #{number} CI triage comment.\n"
    if run["conclusion"] not in {"failure", "timed_out"}:
        return "Non-success event without actionable failure; no comment.\n"
    api("POST", f"/repos/{repository}/issues/{number}/comments", token, {"body": body})
    return f"Created PR #{number} CI triage comment.\n"


def manual_report_event(event, repo, token):
    """Resolve an explicit manual run ID through GitHub, never supplied metadata."""
    value = (event.get("inputs") or {}).get("run_id", "")
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValueError("Manual reporting requires a numeric run_id")
    run = api("GET", f"/repos/{repo}/actions/runs/{value}", token)
    resolved = {"action": "completed", "workflow_run": run}
    if run.get("id") != int(value) or identify(resolved, repo) is None:
        raise ValueError("Manual run is incomplete, unrelated or untrusted")
    return resolved


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        repo = os.environ["GITHUB_REPOSITORY"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid repository")
        if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
            event = manual_report_event(event, repo, os.environ["GITHUB_TOKEN"])
        report = run_report(event, repo, os.environ["GITHUB_TOKEN"],
                            os.getenv("LOCAL_PC_ENABLED", ""))
        if os.getenv("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
                out.write(report)
        print(report.strip())
        return 0
    except (KeyError, ValueError, OSError, HTTPError, URLError, TypeError):
        # Avoid exposing GitHub API bodies or tokens. A reporting problem fails
        # this separate advisory workflow, never touches production or source.
        print("Autonomous CI reporting unavailable; inspect this workflow run.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
