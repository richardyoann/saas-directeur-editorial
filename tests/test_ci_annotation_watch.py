"""CI watcher behavior with mocked GitHub API, without credentials or network."""
import unittest
from unittest.mock import patch
from scripts import ci_annotation_watch as watch

REPO = "richardyoann/saas-directeur-editorial"
RUN = {"id": 123, "name": "Full regression", "status": "completed",
       "conclusion": "success", "head_sha": "a" * 40,
       "head_repository": {"full_name": REPO}}
JOBS = {"total_count": 1, "jobs": [{"check_run_url":
        "https://api.github.com/repos/" + REPO + "/check-runs/888"}]}


class CIAnnotationWatchTests(unittest.TestCase):
    def test_green_with_warning_creates_incident_without_raw_text(self):
        annotation = [{"annotation_level": "warning",
                       "message": "Node.js 20 obsolete SECRET_DO_NOT_PUBLISH"}]
        with patch.object(watch, "api", side_effect=[
            JOBS, annotation, [], {"number": 42}
        ]) as mocked:
            status = watch.monitor(RUN, REPO, "token")
        self.assertIn("Created", status)
        issue = mocked.call_args.args[3]
        self.assertIn("deprecated_node20", issue["body"])
        self.assertIn("success", issue["body"])
        self.assertNotIn("SECRET_DO_NOT_PUBLISH", issue["body"])

    def test_duplicate_run_updates_old_issue(self):
        annotation = [{"annotation_level": "warning", "message": "deprecation"}]
        old = {"number": 15, "state": "open", "body": watch.marker(RUN["id"]) + "\noutdated"}
        with patch.object(watch, "api", side_effect=[JOBS, annotation, [old], old]) as mocked:
            status = watch.monitor(RUN, REPO, "token")
        self.assertIn("Deduplicated", status)
        self.assertEqual(mocked.call_args.args[0], "PATCH")

    def test_green_clean_does_not_create_issue(self):
        with patch.object(watch, "api", side_effect=[JOBS, []]) as mocked:
            status = watch.monitor(RUN, REPO, "token")
        self.assertIn("No warning", status)
        self.assertEqual(mocked.call_count, 2)

    def test_notice_only_for_relevant_deprecation(self):
        counts = watch.summarize([
            {"annotation_level": "notice", "message": "build summary"},
            {"annotation_level": "notice", "message": "ubuntu-latest migration"},
            {"annotation_level": "failure", "message": "test failed"},
        ])
        self.assertEqual(sum(counts.values()), 2)

    def test_fork_and_unknown_workflow_rejected(self):
        candidate = dict(RUN)
        candidate["head_repository"] = {"full_name": "foreign/repo"}
        self.assertFalse(watch.trusted(candidate, REPO))
        candidate["head_repository"] = {"full_name": REPO}
        candidate["name"] = "unknown"
        self.assertFalse(watch.trusted(candidate, REPO))

    def test_malformed_job_listing_fails_closed(self):
        with patch.object(watch, "api", return_value={"total_count": 2, "jobs": [{}]}):
            with self.assertRaises(ValueError):
                watch.collect(RUN, REPO, "token")

    def test_foreign_check_run_url_fails_closed(self):
        bad = {"total_count": 1, "jobs": [{"check_run_url": "https://example.org/x"}]}
        with patch.object(watch, "api", return_value=bad):
            with self.assertRaises(ValueError):
                watch.collect(RUN, REPO, "token")


if __name__ == "__main__":
    unittest.main()
