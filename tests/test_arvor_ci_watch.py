"""No GitHub, Docker, Slack or WSL needed."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from scripts import arvor_ci_watch as ci

HEAD = "a" * 40
BASE = "b" * 40

def pr(number=214):
    return {"number": number, "state": "open", "draft": True,
            "head": {"ref": "ops/arvor-sync", "sha": HEAD, "repo": {"full_name": ci.REPO}},
            "base": {"ref": "main", "sha": BASE}, "updated_at": "2026-10-22T11:00:00Z"}


class AutopilotTests(unittest.TestCase):
    def test_draft_eligible(self):
        self.assertTrue(ci.eligible(pr()))
    def test_fork_and_stale_refs_rejected(self):
        bad = pr()
        bad["head"]["repo"]["full_name"] = "untrusted/repository"
        self.assertFalse(ci.eligible(bad))
        bad = pr()
        bad["head"]["ref"] = "../unsafe"
        self.assertFalse(ci.eligible(bad))
        bad = pr()
        bad["head"]["sha"] = "wrong"
        self.assertFalse(ci.eligible(bad))
    def test_only_recheck_when_sha_or_base_changes(self):
        with TemporaryDirectory() as d:
            folder = Path(d)
            item = pr()
            now = datetime.now(timezone.utc)
            ci.record_outcome(folder, item, "passed", now)
            self.assertFalse(ci.should_run(item, folder, now))
            item["base"]["sha"] = "c" * 40
            self.assertTrue(ci.should_run(item, folder, now))
    def test_controller_validation_rejects_unapproved_sha(self):
        with self.assertRaises(ValueError):
            ci.validate_controller(Path("/tmp"), "unapproved")
    def test_moved_head_prevents_test_execution(self):
        with patch.object(ci, "git", side_effect=["", BASE, "c" * 40]):
            with self.assertRaisesRegex(RuntimeError, "moved"):
                ci.confirmed_shas(Path("/tmp"), pr())
    def test_failure_alert_is_bounded_metadata(self):
        with patch.object(ci, "api", return_value={"ok": True}) as send:
            ci.slack_failure(pr(), "preflight_or_publisher_unavailable", "token", "channel")
            self.assertIn("214", send.call_args.args[2]["text"])
            self.assertNotIn("token", send.call_args.args[2]["text"])
    def test_runs_only_one_pr_per_tick(self):
        with TemporaryDirectory() as d, patch.object(ci, "validate_controller"), \
             patch.object(ci, "discover", return_value=[pr(216), pr(214)]), \
             patch.object(ci, "run_pr", return_value="passed") as runner:
            self.assertEqual(ci.cycle(Path(d), Path(d) / "state", HEAD, "github", "slack", "channel"),
                             [(216, "passed")])
            runner.assert_called_once()
    def test_systemd_credentials_preferred(self):
        with TemporaryDirectory() as d:
            (Path(d)/"github_token").write_text("gh")
            (Path(d)/"slack_token").write_text("slack")
            with patch.dict("os.environ", {"CREDENTIALS_DIRECTORY": d}, clear=True):
                self.assertEqual(ci.configured_tokens(), ("gh", "slack"))
    def test_force_without_explicit_pr_is_rejected(self):
        with self.assertRaises(SystemExit):
            ci.main(["--controller", "/tmp", "--force"])


if __name__ == "__main__":
    unittest.main()
