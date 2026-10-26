"""TLS and credential boundaries, without a live MinIO dependency."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from botocore.httpsession import get_cert_path

from infrastructure.media.s3 import client, MediaStorageError


class S3SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('access', 'secret'):
            p = self.root / name
            p.write_text('synthetic-test-' + name)
            p.chmod(0o600)
        self.env = {
            'MEDIA_S3_ENDPOINT': 'https://127.0.0.1:9000',
            'MEDIA_S3_ACCESS_KEY_FILE': str(self.root / 'access'),
            'MEDIA_S3_SECRET_KEY_FILE': str(self.root / 'secret'),
            'AWS_CA_BUNDLE': get_cert_path(True),
        }

    def test_verified_ca_and_explicit_app_credentials(self):
        with patch.dict(os.environ, self.env, clear=True), patch('boto3.client') as factory:
            client()
        args = factory.call_args.kwargs
        self.assertEqual(args['verify'], self.env['AWS_CA_BUNDLE'])
        self.assertEqual(args['aws_access_key_id'], 'synthetic-test-access')
        self.assertEqual(args['config'].retries['total_max_attempts'], 1)
        self.assertEqual(args['config'].s3['addressing_style'], 'path')

    def test_invalid_config_never_constructs_network_client(self):
        cases = [
            {'MEDIA_S3_ENDPOINT': 'http://127.0.0.1:9000'},
            {'MEDIA_S3_ENDPOINT': 'https://public.example'},
            {'MEDIA_S3_ENDPOINT': 'https://user:password@127.0.0.1'},
            {'AWS_CA_BUNDLE': ''}, {'AWS_CA_BUNDLE': str(self.root / 'absent')},
            {'MEDIA_S3_ACCESS_KEY_FILE': ''}, {'MEDIA_S3_SECRET_KEY_FILE': ''},
            {'MEDIA_S3_ACCESS_KEY': 'injected-admin'},
            {'MEDIA_S3_SECRET_KEY': 'injected-admin'},
        ]
        for override in cases:
            with self.subTest(override=override), patch.dict(os.environ, self.env | override, clear=True), patch('boto3.client') as factory:
                with self.assertRaisesRegex(MediaStorageError, '^media_configuration_invalid$'):
                    client()
                factory.assert_not_called()

    def test_bad_pem_unreadable_credentials_and_sdk_errors_are_redacted(self):
        invalid = self.root / 'bad.pem'
        invalid.write_text('SECRET_SENTINEL')
        for override in ({'AWS_CA_BUNDLE': str(invalid)},
                         {'MEDIA_S3_SECRET_KEY_FILE': str(self.root / 'absent')}, {}):
            with self.subTest(override=override), patch.dict(os.environ, self.env | override, clear=True), patch('boto3.client', side_effect=RuntimeError('SECRET_SENTINEL')):
                with self.assertRaises(MediaStorageError) as caught:
                    client()
                self.assertEqual(str(caught.exception), 'media_configuration_invalid')
                self.assertTrue(caught.exception.__suppress_context__)
