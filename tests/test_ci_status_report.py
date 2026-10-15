"""No network tests for trusted-main GitHub Actions triage reporter."""
import unittest
from unittest.mock import patch

from scripts import ci_status_report as reporter


REPO = "richardyoann/saas-directeur-editorial"
SHA = "a" * 40


def event(conclusion="failure", source="pull_request"):
    return {"action": "completed", "workflow_run": {
        "id": 123, "name": "Full regression", "status": "completed",
        "conclusion": conclusion, "head_sha": SHA,
        "head_branch": "test-fix" if source == "pull_request" else "main",
        "head_repository": {"full_name": REPO}, "event": source,
        "pull_requests": [{"number": 81}] if source == "pull_request" else [],
    }}


class AutomatedTriageTests(unittest.TestCase):
    def test_unrelated_events_are_rejected(self):
        data = event()
        data["workflow_run"]["head_repository"]["full_name"] = "other/repository"
        self.assertIsNone(reporter.identify(data, REPO))
        data = event()
        data["workflow_run"]["name"] = "Unrelated workflow"
        self.assertIsNone(reporter.identify(data, REPO))

    def test_main_release_packet_does_not_claim_deployment(self):
        run = event("success", "push")["workflow_run"]
        report = reporter.release_packet(run, REPO, "false")
        self.assertIn("not performed", report)
        self.assertIn("required for this exact SHA", report)
        self.assertIn("**off**", report)
        self.assertIn(SHA, report)
        self.assertIn("**unknown**", reporter.release_packet(run, REPO, "") )

    def test_stale_head_never_posts(self):
        with patch.object(reporter, "api", return_value={
            "head": {"sha": "b" * 40}, "base": {"ref": "main"}, "state": "open",
        }) as mocked:
            result = reporter.run_report(event(), REPO, "token")
        self.assertIn("Stale", result)
        self.assertEqual(mocked.call_count, 1)

    def test_failure_posts_comment_without_raw_logs(self):
        pr = {"head": {"sha": SHA}, "base": {"ref": "main"}, "state": "open"}
        jobs = {"total_count": 1, "jobs": [{"name": "regression", "conclusion": "failure"}]}
        with patch.object(reporter, "api", side_effect=[pr, jobs, [], {"id": 100}]) as mocked:
            result = reporter.run_report(event(), REPO, "token")
        self.assertIn("Created", result)
        self.assertEqual(mocked.call_args.args[:2], ("POST", f"/repos/{REPO}/issues/81/comments"))
        body = mocked.call_args.args[3]["body"]
        self.assertIn(reporter.MARKER, body)
        self.assertIn("not a code review", body)
        self.assertNotIn("token", body)
        self.assertNotIn("prompt body", body)

    def test_successful_pr_creates_no_spam(self):
        pr = {"head": {"sha": SHA}, "base": {"ref": "main"}, "state": "open"}
        with patch.object(reporter, "api", side_effect=[
            pr, {"total_count": 1, "jobs": [{"name": "test", "conclusion": "success"}]}, []
        ]) as mocked:
            result = reporter.run_report(event("success"), REPO, "token")
        self.assertIn("no redundant", result)
        self.assertEqual(mocked.call_count, 3)

    def test_bot_comment_updated_instead_of_duplicated(self):
        pr = {"head": {"sha": SHA}, "base": {"ref": "main"}, "state": "open"}
        old = {"id": 50, "user": {"type": "Bot"},
               "body": reporter.MARKER + "\n### Automated CI triage — Full regression"}
        with patch.object(reporter, "api", side_effect=[
            pr, {"total_count": 1, "jobs": [{"name": "test", "conclusion": "failure"}]},
            [old], {"id": 50},
        ]) as mocked:
            result = reporter.run_report(event(), REPO, "token")
        self.assertIn("Updated", result)
        self.assertEqual(mocked.call_args.args[0], "PATCH")

    def test_resolved_failure_comment_has_no_stale_repair_instruction(self):
        pr = {"head": {"sha": SHA}, "base": {"ref": "main"}, "state": "open"}
        old = {"id": 50, "user": {"type": "Bot"},
               "body": reporter.MARKER + "\\n### Automated CI triage — Full regression"}
        with patch.object(reporter, "api", side_effect=[
            pr, {"total_count": 1, "jobs": [{"name": "regression", "conclusion": "success"}]},
            [old], {"id": 50},
        ]) as mocked:
            result = reporter.run_report(event("success"), REPO, "token")
        self.assertIn("Updated", result)
        body = mocked.call_args.args[3]["body"]
        self.assertIn("resolved", body.lower())
        self.assertNotIn("Review failing job steps", body)
        self.assertIn(SHA, body)

    def test_failure_includes_reproducible_static_actions_without_log_payload(self):
        data = event()
        data["workflow_run"]["name"] = "Dependency security audit"
        summary = reporter.triage_comment(
            data["workflow_run"], reporter.classify_failure([{
                "name": "audit", "conclusion": "failure"
            }]))
        self.assertIn("pip", summary)
        self.assertIn("manual", summary.lower())
        self.assertNotIn("raw log content", summary)

    def test_multiple_candidate_prs_never_mutate(self):
        e = event()
        e["workflow_run"]["pull_requests"].append({"number": 99})
        with patch.object(reporter, "api") as mocked:
            result = reporter.run_report(e, REPO, "token")
        self.assertIn("No unambiguous", result)
        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
