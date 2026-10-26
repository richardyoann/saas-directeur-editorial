"""Real-probe control flow without any live account or network."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from scripts import check_media_s3 as probe


class MediaProbeTests(unittest.TestCase):
    def run_probe(self, *, delete_code='AccessDenied', upload_error=None, git_error=False, corrupt=False):
        api = MagicMock()
        if delete_code:
            api.delete_object.side_effect = ClientError(
                {'Error': {'Code': delete_code, 'Message': 'SECRET_SENTINEL'}}, 'DeleteObject')
        def put(path, *args):
            if upload_error:
                raise upload_error
            return {'bucket': 'synthetic-media', 'key': 'synthetic-probe',
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        def get(reference, path, *args):
            path.write_bytes(b'corrupt' if corrupt else b'arvor-synthetic-s3-integration-probe\n')
            return path
        stdout = io.StringIO()
        with patch('sys.argv', ['probe', '--write-probe']), \
                patch.object(probe.subprocess, 'check_output', side_effect=OSError('SECRET_SENTINEL') if git_error else None,
                             return_value='a'*40+'\n') as git, \
                patch.object(probe.storage, 'put_file', side_effect=put) as upload, \
                patch.object(probe.storage, 'get_file', side_effect=get), \
                patch.object(probe.storage, 'client', return_value=api), redirect_stdout(stdout):
            code = probe.main()
        self.assertNotIn('SECRET_SENTINEL', stdout.getvalue())
        return code, json.loads(stdout.getvalue()), api, git, upload

    def test_expected_denials_pass_and_git_uses_script_root(self):
        for denial in ('AccessDenied', 'AllAccessDisabled'):
            with self.subTest(denial=denial):
                code, report, api, git, upload = self.run_probe(delete_code=denial)
                self.assertEqual(code, 0)
                self.assertEqual(report['outcome'], 'passed')
                self.assertEqual(report['sha'], 'a'*40)
                self.assertEqual(git.call_args.kwargs['cwd'], Path(probe.__file__).resolve().parents[1])
                self.assertEqual(git.call_args.kwargs['stderr'], subprocess.DEVNULL)
                api.delete_object.assert_called_once_with(Bucket='synthetic-media', Key='synthetic-probe')

    def test_allowed_delete_other_denial_and_network_error_fail(self):
        for options in ({'delete_code': None}, {'delete_code': 'InternalError'},
                        {'upload_error': RuntimeError('SECRET_SENTINEL')}):
            with self.subTest(options=options):
                code, report, *_ = self.run_probe(**options)
                self.assertEqual(code, 1)
                self.assertEqual(report['error'], 'media_s3_probe_failed')
                self.assertNotIn('checks', report)

    def test_git_failure_is_controlled_before_any_write(self):
        code, report, _, _, upload = self.run_probe(git_error=True)
        self.assertEqual(code, 1)
        self.assertEqual(report['error'], 'media_s3_probe_failed')
        upload.assert_not_called()

    def test_corrupt_download_fails_before_delete_check(self):
        code, report, api, *_ = self.run_probe(corrupt=True)
        self.assertEqual(code, 1)
        api.delete_object.assert_not_called()
