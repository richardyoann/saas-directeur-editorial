"""Conservative CI pull-request risk inventory; never edits repository files.

Runs on GitHub's hosted runner with read-only permissions. Findings are
deterministic *review hints*, not an independent security/code approval.
"""
import argparse
import json
import os
from pathlib import PurePosixPath
import subprocess
import sys


SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".sqlite", ".dump")
RELEASE_PATHS = {
    ".github/workflows/local-delivery.yml",
    "scripts/deploy_local.py",
    "docs/AUTONOMOUS_DELIVERY.md",
}
MAX_FILES = 500


def classify(changed):
    paths = sorted(set(changed))
    if len(paths) > MAX_FILES:
        raise ValueError("Too many changed paths to review")
    for path in paths:
        if not path or path.startswith("/") or ".." in PurePosixPath(path).parts or "\n" in path:
            raise ValueError("Invalid path in diff")
    secret = []
    migration = []
    release = []
    dependency = []
    for path in paths:
        basename = PurePosixPath(path).name
        if ((basename == ".env" or basename.startswith(".env.") and basename != ".env.example")
                or basename.endswith(SENSITIVE_SUFFIXES)):
            secret.append(path)
        if path.startswith("migrations/") or path.endswith("/migration.sql") or path == "pilotage/migration.sql":
            migration.append(path)
        if path in RELEASE_PATHS or path.startswith(".github/workflows/"):
            release.append(path)
        if basename in {"requirements.txt", "pyproject.toml", "uv.lock", "poetry.lock"}:
            dependency.append(path)
    code = [p for p in paths if p.endswith((".py", ".js")) and
            not p.startswith(("tests/", "browser_checks/")) and
            not PurePosixPath(p).name.startswith("test_")]
    tests = [p for p in paths if p.startswith(("tests/", "browser_checks/")) or
             PurePosixPath(p).name.startswith("test_")]
    docs = [p for p in paths if p.startswith("docs/") or p in {"README.md", "AGENTS.md"}]
    warnings = []
    if migration:
        warnings.append("migration_requires_manual_authorization")
    if release:
        warnings.append("workflow_or_release_needs_review")
    if dependency:
        warnings.append("dependency_audit_required")
    if code and not tests:
        warnings.append("missing_test_change_review")
    if code and not docs:
        warnings.append("documentation_change_review")
    if not paths:
        warnings.append("no_diff_detected")
    blocking = ["sensitive_file_tracked"] if secret else []
    return {
        "status": "blocked" if blocking else "review_required" if warnings else "checked",
        "changed_files": len(paths),
        "code_files": len(code),
        "test_files": len(tests),
        "doc_files": len(docs),
        "sensitive_paths": secret,
        "migration_paths": migration,
        "release_paths": release,
        "dependency_paths": dependency,
        "blockers": blocking,
        "review_hints": warnings,
        "note": "Heuristic risk inventory only; not a human code review or approval.",
    }


def git_changed_paths(base, head):
    # Refs are supplied as CLI options by the checked-in workflow, never
    # interpolated into a shell command. Use NUL-safe filenames.
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", base, head],
        check=True, capture_output=True
    )
    return [p.decode("utf-8", errors="strict") for p in result.stdout.split(b"\0") if p]


def format_summary(report, sha):
    status = report["status"]
    parts = [
        "## Automated PR change inventory",
        f"Status: **{status}** · Commit: \`{sha}\`",
        f"Changed: {report['changed_files']}; code: {report['code_files']}; tests: {report['test_files']}; docs: {report['doc_files']}.",
    ]
    if report["blockers"]:
        parts.append("**Blocking:** " + ", ".join(report["blockers"]))
    if report["review_hints"]:
        parts.append("Manual review hints: " + ", ".join(report["review_hints"]))
    parts.extend([
        "This check never approves, fixes or deploys any change.",
        "Schema, data, runtime, secrets and release gates remain subject to separate review.",
    ])
    return "\n\n".join(parts) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--sha", default=os.getenv("GITHUB_SHA", "local"))
    args = parser.parse_args(argv)
    try:
        report = classify(git_changed_paths(args.base, args.head))
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError):
        # A missing/incomplete comparison cannot be reported as green.
        report = {"status": "blocked", "changed_files": 0, "code_files": 0,
                  "test_files": 0, "doc_files": 0, "sensitive_paths": [],
                  "migration_paths": [], "release_paths": [],
                  "dependency_paths": [], "blockers": ["risk_scan_incomplete"],
                  "review_hints": []}
    print(json.dumps(report, sort_keys=True))
    summary = format_summary(report, args.sha)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
