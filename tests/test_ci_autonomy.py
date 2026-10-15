"""Unit tests for deterministic PR risk inventory (no GitHub access)."""
import unittest
from unittest.mock import patch

from scripts import ci_autonomy as audit


class RiskInventoryTests(unittest.TestCase):
    def test_no_changes_is_not_an_approval(self):
        result = audit.classify([])
        self.assertEqual(result["status"], "review_required")
        self.assertIn("no_diff_detected", result["review_hints"])

    def test_changes_with_tests_and_docs(self):
        result = audit.classify([
            "apps/api/main.py", "tests/test_generate.py", "docs/EDITORIAL_WORKFLOW.md"
        ])
        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["code_files"], 1)
        self.assertEqual(result["test_files"], 1)
        self.assertEqual(result["doc_files"], 1)

    def test_code_without_tests_or_docs_is_flagged_not_auto_fixed(self):
        result = audit.classify(["apps/api/main.py"])
        self.assertEqual(result["status"], "review_required")
        self.assertIn("missing_test_change_review", result["review_hints"])
        self.assertIn("documentation_change_review", result["review_hints"])

    def test_sensitive_files_block_and_do_not_display_contents(self):
        result = audit.classify([".env", "runtime/database.dump", "apps/main.py"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("sensitive_file_tracked", result["blockers"])
        self.assertEqual(result["sensitive_paths"], [".env", "runtime/database.dump"])

    def test_migrations_and_deployment_need_manual_review(self):
        result = audit.classify([
            "pilotage/migration.sql", "migrations/002.sql",
            ".github/workflows/local-delivery.yml", "requirements.txt"
        ])
        self.assertIn("migration_requires_manual_authorization", result["review_hints"])
        self.assertIn("workflow_or_release_needs_review", result["review_hints"])
        self.assertIn("dependency_audit_required", result["review_hints"])
        self.assertNotEqual(result["status"], "checked")

    def test_example_env_is_not_secret(self):
        result = audit.classify([".env.example", "README.md"])
        self.assertEqual(result["status"], "checked")

    def test_invalid_or_too_many_paths_fail_closed(self):
        for paths in (["../outside.py"], ["/root/.env"], ["bad\nname.py"], ["a.py"] * 0 + [str(n) for n in range(501)]):
            with self.subTest(paths=paths[:2]), self.assertRaises(ValueError):
                audit.classify(paths)

    def test_git_diff_invoked_without_shell(self):
        with patch.object(audit.subprocess, "run") as run:
            run.return_value.stdout = b"apps/api/main.py\0tests/test_main.py\0"
            paths = audit.git_changed_paths("origin/main", "HEAD")
        self.assertEqual(paths, ["apps/api/main.py", "tests/test_main.py"])
        self.assertEqual(run.call_args.args[0][:3], ["git", "diff", "--name-only"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_summary_does_not_claim_approval(self):
        report = audit.classify(["docs/EDITORIAL_WORKFLOW.md"])
        result = audit.format_summary(report, "abcdef")
        self.assertIn("not a human", report["note"])
        self.assertIn("never approves", result)


if __name__ == "__main__":
    unittest.main()
