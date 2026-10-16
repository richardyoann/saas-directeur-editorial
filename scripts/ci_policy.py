"""Fail-closed, dependency-free guardrails for repository GitHub Actions workflows.

No runtime secrets, outbound network traffic, or changes to production.
Run on every PR, push to main, and daily.  Maintain the approved SHA allowlist
via a reviewed PR when intentionally upgrading actions to future versions.
"""
from pathlib import Path
import re
import sys

REQUIRED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",  # v7.0.1
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",  # v7.0.0
}
SHA = re.compile(r"^[0-9a-f]{40}$")
USES = re.compile(r"^\s*-\s*uses:\s*(\S+)\s*(?:#.*)?$")
UNPINNED_RUNNER = re.compile(r"^\s*runs-on:\s*ubuntu-latest(?:\s|$)")
UNSAFE_EVENT = re.compile(r"^\s*pull_request_target\s*:")


def audit_workflow(name: str, source: str) -> list[str]:
    problems = []
    if not re.search(r"(?m)^permissions:\s*$", source):
        problems.append(f"{name}: missing explicit top-level permissions")
    for number, line in enumerate(source.splitlines(), start=1):
        action = USES.match(line)
        if action:
            spec = action.group(1)
            if spec.startswith("./") or spec.startswith("docker://"):
                continue
            if "@" not in spec:
                problems.append(f"{name}:{number}: action missing pinned SHA")
                continue
            owner, ref = spec.rsplit("@", 1)
            if not SHA.fullmatch(ref):
                problems.append(f"{name}:{number}: action not pinned to immutable SHA")
            expected = REQUIRED_ACTIONS.get(owner)
            if expected and ref != expected:
                problems.append(f"{name}:{number}: outdated or unreviewed {owner} SHA")
        if UNPINNED_RUNNER.search(line):
            problems.append(f"{name}:{number}: ubuntu-latest changes without review")
        if "permissions: write-all" in line or re.search(r"^\s*permissions:\s*write-all\s*$", line):
            problems.append(f"{name}:{number}: overly broad token permissions")
        if UNSAFE_EVENT.search(line):
            problems.append(f"{name}:{number}: pull_request_target requires separate review")
    return problems


def audit_repository(root: Path) -> list[str]:
    folder = root / ".github" / "workflows"
    if not folder.is_dir():
        return ["missing .github/workflows"]
    candidates = sorted(list(folder.glob("*.yml")) + list(folder.glob("*.yaml")))
    if not candidates:
        return ["no GitHub Actions workflows found"]
    issues = []
    for path in candidates:
        try:
            issues.extend(audit_workflow(path.name, path.read_text(encoding="utf-8")))
        except OSError:
            issues.append(f"{path.name}: unreadable workflow")
    if not (root / ".github" / "dependabot.yml").is_file():
        issues.append("Dependabot configuration missing")
    return issues


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    problems = audit_repository(repo)
    if problems:
        for item in problems:
            print(f"::error::{item}")
        print(f"CI policy: {len(problems)} finding(s)")
        return 1
    print("CI policy: pinned actions, stable hosted runners and Dependabot verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
