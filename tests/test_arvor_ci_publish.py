import unittest
from unittest.mock import patch
from scripts.arvor_ci_evidence import seal
from scripts.arvor_ci_publish import publish, summary
from test_arvor_ci_evidence import example, KEY, SHA


class PublisherTests(unittest.TestCase):
    def test_summary_excludes_logs(self):
        text = summary(seal(example(), SHA, KEY))
        self.assertIn('9/9', text)
        self.assertNotIn('secret', text)

    def test_stale_pr_refuses_every_write(self):
        envelope = seal(example(), SHA, KEY)
        with patch('scripts.arvor_ci_publish.request_json', return_value={
            'state': 'open', 'head': {'sha': 'b' * 40},
            'base': {'ref': 'main', 'sha': 'b'*40}}) as api:
            with self.assertRaisesRegex(ValueError, 'stale'):
                publish(envelope, SHA, KEY, 216, 'GHTOKEN', 'SLACKTOKEN', 'CABC123')
            self.assertEqual(api.call_count, 1)

    def test_main_moved_after_ci_refuses_publication(self):
        envelope = seal(example(), SHA, KEY)
        with patch('scripts.arvor_ci_publish.request_json', return_value={
            'state': 'open',
            'head': {'sha': SHA, 'repo': {'full_name': 'richardyoann/saas-directeur-editorial'}},
            'base': {'ref': 'main', 'sha': 'c' * 40},
        }) as api:
            with self.assertRaisesRegex(ValueError, 'stale'):
                publish(envelope, SHA, KEY, 216, 'GHTOKEN', 'SLACKTOKEN', 'CABC123')
            self.assertEqual(api.call_count, 1)

    def test_valid_publish_but_not_an_approval(self):
        envelope = seal(example(), SHA, KEY)
        def fake_api(url, token, *, payload=None):
            if url.endswith('/pulls/216'):
                return {'state': 'open', 'head': {'sha': SHA, 'repo': {'full_name': 'richardyoann/saas-directeur-editorial'}}, 'base': {'ref': 'main', 'sha': 'b'*40}}
            if 'slack.com' in url:
                self.assertIn('Aucune fusion ni livraison', payload['text'])
                return {'ok': True, 'ts': '123.456'}
            if '/statuses/' in url:
                self.assertEqual(payload['state'], 'success')
                self.assertEqual(payload['context'], 'arvor/local-ci')
            return {}
        with patch('scripts.arvor_ci_publish.request_json', side_effect=fake_api) as api:
            self.assertEqual(publish(envelope, SHA, KEY, 216, 'GHTOKEN', 'SLACKTOKEN', 'CABC123'), 'success')
            self.assertEqual(api.call_count, 4)

    def test_failed_gate_never_publishes_green(self):
        report = example()
        report['gates']['video_75'] = {'status': 'failed', 'exit_code': 1, 'tests': 0, 'skipped': 0}
        envelope = seal(report, SHA, KEY)
        statuses = []
        def fake_api(url, token, *, payload=None):
            if url.endswith('/pulls/216'):
                return {'state': 'open', 'head': {'sha': SHA, 'repo': {'full_name': 'richardyoann/saas-directeur-editorial'}}, 'base': {'ref': 'main', 'sha': 'b'*40}}
            if '/statuses/' in url:
                statuses.append(payload['state'])
            return {'ok': True}
        with patch('scripts.arvor_ci_publish.request_json', side_effect=fake_api):
            self.assertEqual(publish(envelope, SHA, KEY, 216, 'GHTOKEN', 'SLACKTOKEN', 'CABC123'), 'failure')
        self.assertEqual(statuses, ['failure'])

if __name__ == '__main__': unittest.main()
