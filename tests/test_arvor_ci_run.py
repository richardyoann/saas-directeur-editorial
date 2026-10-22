"""Fail-closed image selection tests without running Docker."""
import os
from unittest.mock import patch
import unittest
from scripts import arvor_ci_run as runner


class RunPreflightTests(unittest.TestCase):
    def test_missing_approved_image_ids_blocks(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(runner, 'cmd') as command:
            self.assertFalse(runner.check_approved_images())
            command.assert_not_called()

    def test_malformed_image_id_blocks_before_inspection(self):
        env = {'ARVOR_CI_IMAGE_ID_312': 'sha256:' + 'a' * 63,
               'ARVOR_CI_IMAGE_ID_314': 'sha256:' + 'b' * 64,
               'ARVOR_CI_POSTGRES_IMAGE_ID': 'sha256:' + 'c' * 64}
        with patch.dict(os.environ, env, clear=True), patch.object(runner, 'cmd') as command:
            self.assertFalse(runner.check_approved_images())
            command.assert_not_called()

    def test_swapped_tag_blocks(self):
        env = {'ARVOR_CI_IMAGE_ID_312': 'sha256:' + 'a' * 64,
               'ARVOR_CI_IMAGE_ID_314': 'sha256:' + 'b' * 64,
               'ARVOR_CI_POSTGRES_IMAGE_ID': 'sha256:' + 'c' * 64}
        def fake_cmd(args, **kwargs):
            class Result:
                returncode = 0
                stdout = 'sha256:' + 'd' * 64
            return Result()
        with patch.dict(os.environ, env, clear=True), patch.object(runner, 'cmd', side_effect=fake_cmd):
            self.assertFalse(runner.check_approved_images())

    def test_exact_image_ids_accepted(self):
        ids = {'arvor-ci:3.12': 'sha256:' + 'a' * 64,
               'arvor-ci:3.14': 'sha256:' + 'b' * 64,
               'postgres:16': 'sha256:' + 'c' * 64}
        env = {name: ids[tag] for tag, name in runner.IMAGE_ENV_IDS.items()}
        def fake_cmd(args, **kwargs):
            class Result:
                returncode = 0
                stdout = ids[args[-1]] + '\n'
            return Result()
        with patch.dict(os.environ, env, clear=True), patch.object(runner, 'cmd', side_effect=fake_cmd) as command:
            self.assertTrue(runner.check_approved_images())
            self.assertEqual(command.call_count, 3)

    def test_docker_gate_rejects_online_database(self):
        with self.assertRaises(ValueError):
            runner.docker_gate('/tmp', 'test', ('arvor-ci:3.12', ['true']), needs_db=True, online=True)


if __name__ == '__main__':
    unittest.main()
