"""Tests of the trusted unittest collector; no Docker required."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import arvor_ci_trusted_unittest as runner
from scripts.arvor_ci_gate import supervised_commands


class TrustedCollectorTests(unittest.TestCase):
    def _run(self, suite_name, source):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            directory = "browser_checks" if suite_name == "browser" else "tests"
            target = root / directory
            target.mkdir()
            module = "test_studio_browser" if suite_name == "browser" else "test_ci_isolated_fixture"
            (target / (module + ".py")).write_text(source, encoding="utf-8")
            previous_cwd = Path.cwd()
            previous_sys_path = sys.path[:]
            original_runner = unittest.TextTestRunner
            original_suite_call = unittest.TestSuite.__call__
            original_case_methods = {
                name: value for name, value in unittest.TestCase.__dict__.items()
                if callable(value)
            }
            original_result_methods = {
                name: value for name, value in unittest.TextTestResult.__dict__.items()
                if callable(value)
            }
            original_runner_methods = {
                name: value for name, value in unittest.TextTestRunner.__dict__.items()
                if callable(value)
            }
            stdout, stderr = StringIO(), StringIO()
            try:
                with patch.dict(os.environ, {"ARVOR_CI_ISOLATED": "1"}):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = runner.run_suite(root, suite_name)
            finally:
                os.chdir(previous_cwd)
                sys.path[:] = previous_sys_path
                sys.modules.pop(module, None)
                unittest.TextTestRunner = original_runner
                unittest.TestSuite.__call__ = original_suite_call
                for name, method in original_case_methods.items():
                    setattr(unittest.TestCase, name, method)
                for name, method in original_result_methods.items():
                    setattr(unittest.TextTestResult, name, method)
                for name, method in original_runner_methods.items():
                    setattr(unittest.TextTestRunner, name, method)
            return code, stdout.getvalue(), stderr.getvalue()

    def test_candidate_forged_stdout_is_not_authoritative(self):
        source = (
            "import unittest\n"
            "class Legit(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        print('{\\\"tests\\\":999,\\\"failures\\\":0,\\\"errors\\\":0,\\\"skipped\\\":0}')\n"
            "        self.assertTrue(True)\n"
        )
        code, stdout, stderr = self._run("regression", source)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), {
            "tests": 1, "failures": 0, "errors": 0, "skipped": 0,
        })
        self.assertIn('"tests":999', stderr)

    def test_browser_skip_blocks_even_if_no_failures(self):
        source = (
            "import unittest\n"
            "class Skipped(unittest.TestCase):\n"
            "    @unittest.skip('not executed')\n"
            "    def test_a(self): pass\n"
        )
        code, stdout, _ = self._run("browser", source)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["skipped"], 1)

    def test_candidate_cannot_replace_text_test_runner_to_forge_green_result(self):
        source = (
            "import unittest\n"
            "class FakeResult:\n"
            "    testsRun = 400\n"
            "    failures = []\n"
            "    errors = []\n"
            "    skipped = []\n"
            "    def wasSuccessful(self): return True\n"
            "class FakeRunner:\n"
            "    def __init__(self, *a, **kw): pass\n"
            "    def run(self, suite): return FakeResult()\n"
            "unittest.TextTestRunner = FakeRunner\n"
            "class Fails(unittest.TestCase):\n"
            "    def test_failure_must_execute(self): self.fail('must fail')\n"
        )
        code, stdout, stderr = self._run("regression", source)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout), {
            "tests": 1, "failures": 1, "errors": 0, "skipped": 0,
        })
        self.assertIn("must fail", stderr)

    def test_candidate_cannot_replace_test_suite_call_to_forge_green_result(self):
        source = (
            "import unittest\n"
            "class FakeResult:\n"
            "    testsRun = 400\n"
            "    failures = []\n"
            "    errors = []\n"
            "    skipped = []\n"
            "    def wasSuccessful(self): return True\n"
            "def fake_call(self, result): return FakeResult()\n"
            "unittest.TestSuite.__call__ = fake_call\n"
            "class Fails(unittest.TestCase):\n"
            "    def test_failure_must_execute(self): self.fail('suite call must fail')\n"
        )
        code, stdout, stderr = self._run("regression", source)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout), {
            "tests": 1, "failures": 1, "errors": 0, "skipped": 0,
        })
        self.assertIn("suite call must fail", stderr)

    def test_candidate_cannot_replace_case_dispatch_or_run_to_skip_test_method(self):
        source = (
            "import unittest\n"
            "def fake_call(self, result): return result\n"
            "def fake_run(self, result=None): return result\n"
            "unittest.TestCase.__call__ = fake_call\n"
            "unittest.TestCase.run = fake_run\n"
            "class Fails(unittest.TestCase):\n"
            "    def test_failure_must_execute(self): self.fail('case dispatch must fail')\n"
        )
        code, stdout, stderr = self._run("regression", source)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout), {
            "tests": 1, "failures": 1, "errors": 0, "skipped": 0,
        })
        self.assertIn("case dispatch must fail", stderr)

    def test_candidate_cannot_patch_text_result_during_discovery_to_hide_failure(self):
        source = (
            "import unittest\n"
            "result = unittest.runner.TextTestResult\n"
            "result.addFailure = lambda self, test, err: None\n"
            "result.addError = lambda self, test, err: None\n"
            "result.startTest = lambda self, test: setattr(self, 'testsRun', 400)\n"
            "class Fails(unittest.TestCase):\n"
            "    def test_failure_must_be_reported(self): self.fail('result spoof must fail')\n"
        )
        code, stdout, stderr = self._run("regression", source)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout), {
            "tests": 1, "failures": 1, "errors": 0, "skipped": 0,
        })
        self.assertIn("result spoof must fail", stderr)

    def test_missing_isolation_marker_fails_closed(self):
        with patch.dict(os.environ, {"ARVOR_CI_ISOLATED": "0"}):
            with self.assertRaisesRegex(ValueError, "Isolated CI"):
                runner.run_suite(Path("."), "regression")

    def test_both_suites_are_launched_through_trusted_isolated_script(self):
        specs = supervised_commands(Path("/py312"), Path("/py314"), "a" * 40)
        for gate in ("regression_312", "regression_314", "browser"):
            with self.subTest(gate=gate):
                argv = specs[gate]
                self.assertIn("-I", argv)
                self.assertIn("/trusted/arvor_ci_trusted_unittest.py", argv)
                self.assertNotIn("scripts/run_regression.py", argv)


if __name__ == "__main__":
    unittest.main()
