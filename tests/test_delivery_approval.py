import unittest
from scripts.validate_delivery_approval import REPOSITORY, validate


class ApprovalTests(unittest.TestCase):
    def test_exact_current_main(self):
        sha = "a" * 40
        self.assertEqual(validate("delivery-approved/" + sha, REPOSITORY, sha, sha), sha)

    def test_invalid_or_stale_approvals(self):
        sha = "a" * 40
        for ref, repo, current, branch in [
            ("delivery-approved/" + sha, REPOSITORY, "b" * 40, sha),
            ("delivery-approved/" + sha, REPOSITORY, sha, "b" * 40),
            ("delivery-approved/" + sha, "other/repo", sha, sha),
            ("delivery-approved/main", REPOSITORY, sha, sha),
            ("delivery-approved/" + sha + "\n", REPOSITORY, sha, sha),
            ("delivery-approved/" + "A" * 40, REPOSITORY, sha, sha),
        ]:
            with self.subTest(ref=ref, repo=repo, current=current, branch=branch):
                with self.assertRaises(ValueError):
                    validate(ref, repo, current, branch)
