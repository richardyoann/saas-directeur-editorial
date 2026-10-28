"""Unit tests for fail-closed Actions configuration scanning."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.ci_policy import audit_repository, audit_workflow, REQUIRED_ACTIONS


def workflow(action, runner="ubuntu-24.04"):
    return ("name: test\non: [pull_request]\npermissions:\n  contents: read\n"
            f"jobs:\n  checks:\n    runs-on: {runner}\n    steps:\n"
            f"      - uses: {action}\n")


class CIPolicyTests(unittest.TestCase):
    def test_approved_sha_and_pinned_runner(self):
        source = workflow("actions/checkout@" + REQUIRED_ACTIONS["actions/checkout"])
        self.assertEqual(audit_workflow("ci.yml", source), [])

    def test_outdated_node20_checkout_is_rejected(self):
        source = workflow("actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683")
        self.assertTrue(any("outdated" in s for s in audit_workflow("ci.yml", source)))

    def test_mutable_tag_and_ubuntu_latest_are_rejected(self):
        source = workflow("actions/setup-python@v5", "ubuntu-latest")
        issues = audit_workflow("ci.yml", source)
        self.assertTrue(any("immutable SHA" in s for s in issues))
        self.assertTrue(any("ubuntu-latest" in s for s in issues))

    def test_dangerous_events_and_missing_permissions_are_rejected(self):
        source = workflow("actions/checkout@" + REQUIRED_ACTIONS["actions/checkout"])
        source = source.replace("  contents: read\n", "").replace(
            "on: [pull_request]", "on:\n  pull_request_target:"
        ).replace("permissions:\n", "")
        problems = audit_workflow("ci.yml", source)
        self.assertTrue(any("permissions" in s for s in problems))
        self.assertTrue(any("pull_request_target" in s for s in problems))

    def test_self_hosted_workflow_requires_exact_sha_variable(self):
        source = workflow("actions/checkout@" + REQUIRED_ACTIONS["actions/checkout"],
                          "[self-hosted, Linux, editorial-pc]")
        issues = audit_workflow("delivery.yml", source)
        self.assertTrue(any("exact-SHA" in item for item in issues))
        source = source.replace("    steps:", "    if: vars.LOCAL_PC_APPROVED_SHA != ''\n    steps:")
        self.assertEqual(audit_workflow("delivery.yml", source), [])

    def test_repository_discovery_requires_dependabot(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            folder = root / ".github" / "workflows"
            folder.mkdir(parents=True)
            (folder / "test.yml").write_text(
                workflow("actions/checkout@" + REQUIRED_ACTIONS["actions/checkout"]),
                encoding="utf-8"
            )
            self.assertIn("Dependabot configuration missing", audit_repository(root))
            (root / ".github" / "dependabot.yml").write_text("version: 2\n", encoding="utf-8")
            self.assertEqual(audit_repository(root), [])


if __name__ == "__main__":
    unittest.main()
