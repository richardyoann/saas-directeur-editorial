"""Static contract: a private PC delivery needs approval of the exact SHA."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/local-delivery.yml"


class DeliveryApprovalGateTests(unittest.TestCase):
    def test_default_run_requires_two_independent_explicit_variables(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("vars.LOCAL_PC_ENABLED == 'true'", text)
        self.assertIn(
            "vars.LOCAL_PC_APPROVED_SHA == github.event.workflow_run.head_sha", text
        )
        self.assertIn("github.event.workflow_run.conclusion == 'success'", text)
        self.assertIn("github.event.workflow_run.event == 'push'", text)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", text)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", text)
        self.assertIn("runs-on: [self-hosted, Linux, editorial-pc]", text)

    def test_approval_guard_is_executed_before_install(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("name: Verify deployment SHA approval", text)
        self.assertIn('[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]', text)
        self.assertIn('[[ "$APPROVED_SHA" == "$EXPECTED_SHA" ]]', text)
        self.assertIn('[[ "$PC_ENABLED" == "true" ]]', text)
        self.assertLess(text.index("name: Verify deployment SHA approval"),
                        text.index("name: Prepare test dependencies and disposable DB"))
        self.assertLess(text.index("name: Verify deployment SHA approval"),
                        text.index("name: Candidate install, regression, real HTTP and rollback"))

    def test_approval_is_not_a_default_or_unconditional_flag(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^\s*LOCAL_PC_APPROVED_SHA:\s*[0-9a-f]{40}\s*$")
        self.assertIn("vars.LOCAL_PC_APPROVED_SHA", text)
        self.assertNotIn("workflow_dispatch:", text)
        self.assertIn("persist-credentials: false", text)


if __name__ == "__main__":
    unittest.main()
