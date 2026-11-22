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
    # A self-hosted runner executes on the private PC. Every such workflow must
    # be gated by the administrator-controlled exact SHA variable, including
    # approval branches created through the `create` event.
    if re.search(r"(?m)^\s*runs-on:\s*\[[^\]]*self-hosted", source):
        if "vars.LOCAL_PC_APPROVED_SHA" not in source:
            problems.append(f"{name}: self-hosted job lacks exact-SHA repository approval")
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



def audit_secret_configuration(root: Path) -> list[str]:
    """Reject inline production credentials and require external secret files."""
    target = root / "compose.yml"
    if not target.is_file():
        return []
    try:
        source = target.read_text(encoding="utf-8")
    except OSError:
        return ["compose.yml: unreadable secret configuration"]
    errors = []
    for name in ("POSTGRES_PASSWORD_FILE", "MINIO_ROOT_USER_FILE", "MINIO_ROOT_PASSWORD_FILE"):
        if name + ":" not in source:
            errors.append("compose.yml: missing " + name)
    if re.search(r"(?m)^\s*(?:POSTGRES_PASSWORD|MINIO_ROOT_USER|MINIO_ROOT_PASSWORD)\s*:", source):
        errors.append("compose.yml: inline credentials are forbidden")
    for name in ("ARVOR_POSTGRES_PASSWORD_FILE", "ARVOR_MINIO_ROOT_USER_FILE",
                 "ARVOR_MINIO_ROOT_PASSWORD_FILE"):
        if "$" + "{" + name + ":?" not in source:
            errors.append("compose.yml: external path must be mandatory: " + name)
    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    problems = audit_repository(repo) + audit_secret_configuration(repo)
    if problems:
        for item in problems:
            print(f"::error::{item}")
        print(f"CI policy: {len(problems)} finding(s)")
        return 1
    print("CI policy: pinned actions, stable hosted runners and Dependabot verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
