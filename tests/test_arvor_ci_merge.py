from datetime import datetime, timezone, timedelta
import hashlib
import json
import unittest
from scripts.arvor_ci_merge import validate, REPO


class MergeQualificationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.review = json.dumps({'head': 'a'*40, 'base': 'b'*40,
            'blocking_findings': 0, 'kind': 'independent-automated-review'}).encode()
        self.manifest = {'schema': 'arvor-merge-qualification-v1', 'repo': REPO,
            'pr': 214, 'head': 'a'*40, 'base': 'b'*40, 'status': 'success',
            'finished_at': self.now.isoformat(),
            'review_sha256': hashlib.sha256(self.review).hexdigest(),
            'checks': {name: 'passed' for name in ('python312', 'python314', 'regression',
                'postgres', 'browser', 'dependencies', 'secrets', 'supply_chain', 'syntax',
                'review', 'provenance', 'video75', 'sixteen_gates', 'attestation')}}

    def check(self):
        return validate(self.manifest, 214, 'a'*40, 'b'*40, self.review, self.now)

    def test_complete_qualification(self):
        self.assertTrue(self.check())

    def test_changed_identity_or_failed_check_rejected(self):
        for field in ('head', 'base', 'repo', 'status', 'review_sha256'):
            with self.subTest(field=field):
                original = self.manifest[field]
                self.manifest[field] = 'changed'
                with self.assertRaises(ValueError): self.check()
                self.manifest[field] = original
        self.manifest['checks']['browser'] = 'failed'
        with self.assertRaises(ValueError): self.check()

    def test_missing_expired_and_blocking_proof_rejected(self):
        del self.manifest['checks']['video75']
        with self.assertRaises(ValueError): self.check()
        self.setUp()
        self.manifest['finished_at'] = (self.now - timedelta(hours=3)).isoformat()
        with self.assertRaises(ValueError): self.check()
        self.setUp()
        self.review = self.review.replace(b'"blocking_findings": 0', b'"blocking_findings": 1')
        self.manifest['review_sha256'] = hashlib.sha256(self.review).hexdigest()
        with self.assertRaises(ValueError): self.check()

    def test_controller_requires_independent_bootstrap(self):
        self.manifest['pr'] = 215
        with self.assertRaises(ValueError):
            validate(self.manifest, 215, 'a'*40, 'b'*40, self.review, self.now)
        self.manifest['checks']['independent_bootstrap'] = 'passed'
        self.assertTrue(validate(self.manifest, 215, 'a'*40, 'b'*40, self.review, self.now))
