"""Trusted unittest collector for the host-supervised CI.

This file must be installed in /trusted from the independently reviewed
controller checkout. Invoke it with Python -I so candidate sitecustomize and
PYTHONPATH cannot replace the runner before test discovery. Candidate tests
still execute as untrusted code inside the isolated Docker container.
"""
import argparse
from contextlib import redirect_stdout
import inspect
import json
import os
from pathlib import Path
import sys
import unittest

# Freeze the framework entry points before importing candidate test modules.
# Test modules are executable candidate code and can mutate attributes on the
# shared ``unittest`` module during discovery. Looking up TextTestRunner after
# discovery lets such a module replace the runner with a fake green result.
_TRUSTED_TEST_SUITE = unittest.TestSuite
_TRUSTED_TEST_LOADER = unittest.TestLoader
_TRUSTED_TEXT_TEST_RUNNER = unittest.TextTestRunner
_TRUSTED_TEXT_TEST_RUNNER_METHODS = {
    name: value for name, value in unittest.TextTestRunner.__dict__.items()
    if callable(value)
}
_TRUSTED_TEXT_TEST_RESULT = unittest.TextTestResult
_TRUSTED_TEXT_TEST_RESULT_METHODS = {
    name: value for name, value in unittest.TextTestResult.__dict__.items()
    if callable(value)
}
_TRUSTED_SUITE_RUN = unittest.TestSuite.run
_TRUSTED_SUITE_COUNT = unittest.TestSuite.countTestCases
_TRUSTED_SUITE_ITER = unittest.TestSuite.__iter__
_TRUSTED_TEST_CASE = unittest.TestCase
_TRUSTED_TEST_CASE_RUN = unittest.TestCase.run
_TRUSTED_TEST_CASE_METHODS = {
    name: value for name, value in unittest.TestCase.__dict__.items()
    if callable(value)
}
_TRUSTED_SKIP_TEST = unittest.SkipTest
_TRUSTED_ASSERTION_ERROR = unittest.TestCase.failureException


def run_suite(root: Path, suite_name: str):
    if os.environ.get("ARVOR_CI_ISOLATED") != "1":
        raise ValueError("Isolated CI marker is required")
    root = root.resolve(strict=True)
    if not root.is_dir() or suite_name not in ("regression", "browser"):
        raise ValueError("Unsupported CI suite")
    os.chdir(root)
    sys.path.insert(0, str(root))
    # Preserve the standard library runner and reporter, imported before
    # candidate code is made importable, and do not execute a candidate
    # wrapper such as scripts/run_regression.py.
    suite = _TRUSTED_TEST_SUITE()
    # Construct before discovery imports candidate modules. Also keep the
    # bound method, so replacing unittest.TextTestRunner or its class method
    # during discovery cannot replace the execution/reporting operation.
    test_runner = _TRUSTED_TEXT_TEST_RUNNER(verbosity=2, stream=sys.stderr)
    execute_suite = test_runner.run
    observed = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    def restore_result_methods(result):
        for name, method in _TRUSTED_TEXT_TEST_RESULT_METHODS.items():
            setattr(_TRUSTED_TEXT_TEST_RESULT, name, method)
        # Keep instance dispatch pinned too; the test object can reach the
        # result through unittest's private _Outcome member.
        for name, method in _TRUSTED_TEXT_TEST_RESULT_METHODS.items():
            setattr(result, name, method.__get__(result, _TRUSTED_TEXT_TEST_RESULT))

    class TrustedCaseProxy:
        """Keep candidate changes to unittest dispatch from skipping a case."""
        def __init__(self, case):
            self._case = case

        @property
        def __class__(self):
            # unittest uses this for class/module fixtures and display.
            return self._case.__class__

        def __getattr__(self, name):
            return getattr(self._case, name)

        def __call__(self, result):
            # A test module can patch unittest.TestCase methods during import.
            # Restore the framework's captured callable methods before each
            # invocation and call the captured base runner, bypassing a
            # candidate-overridden TestCase.__call__ or TestCase.run.
            for name, method in _TRUSTED_TEST_CASE_METHODS.items():
                setattr(_TRUSTED_TEST_CASE, name, method)
            for name, method in _TRUSTED_TEXT_TEST_RESULT_METHODS.items():
                setattr(_TRUSTED_TEXT_TEST_RESULT, name, method)
            observed["tests"] += 1
            restore_result_methods(result)

            case = self._case
            method_name = getattr(case, "_testMethodName", "")
            callbacks = ["setUp", method_name, "tearDown", "asyncSetUp", "asyncTearDown"]
            originals = {}

            def wrap_callback(callback):
                if inspect.iscoroutinefunction(callback):
                    async def wrapped(*args, **kwargs):
                        try:
                            return await callback(*args, **kwargs)
                        except BaseException as error:
                            record(error)
                            raise
                        finally:
                            restore_result_methods(result)
                else:
                    def wrapped(*args, **kwargs):
                        try:
                            return callback(*args, **kwargs)
                        except BaseException as error:
                            record(error)
                            raise
                        finally:
                            restore_result_methods(result)
                return wrapped

            def record(error):
                if isinstance(error, _TRUSTED_SKIP_TEST):
                    observed["skipped"] += 1
                elif isinstance(error, _TRUSTED_ASSERTION_ERROR):
                    expected = (getattr(case.__class__, "__unittest_expecting_failure__", False)
                                or getattr(getattr(case, method_name, None),
                                           "__unittest_expecting_failure__", False))
                    if not expected:
                        observed["failures"] += 1
                else:
                    observed["errors"] += 1

            for name in callbacks:
                callback = getattr(case, name, None)
                if callable(callback):
                    originals[name] = callback
                    setattr(case, name, wrap_callback(callback))
            try:
                return _TRUSTED_TEST_CASE_RUN(case, result)
            finally:
                for name, callback in originals.items():
                    setattr(case, name, callback)
                restore_result_methods(result)

    def flatten_tests(node):
        if isinstance(node, _TRUSTED_TEST_SUITE):
            for child in _TRUSTED_SUITE_ITER(node):
                yield from flatten_tests(child)
        else:
            yield TrustedCaseProxy(node)
    targets = (
        (("tests", "test_*.py"), ("pilotage", "test_*.py"))
        if suite_name == "regression" else
        (("browser_checks", "test_studio_browser.py"),)
    )
    for directory, pattern in targets:
        if (root / directory).is_dir():
            suite.addTests(_TRUSTED_TEST_LOADER().discover(
                str(root / directory), pattern=pattern))
    # Keep candidate stdout separate from the one authoritative JSON result.
    with redirect_stdout(sys.stderr):
        # unittest.TextTestRunner invokes ``suite(result)``, resolving the
        # special method on the candidate-mutable TestSuite class. Give it a
        # local proxy whose call delegates to the saved stdlib suite runner.
        # This prevents a test module replacing TestSuite.__call__ during
        # discovery from returning a fabricated successful result.
        class TrustedSuiteProxy:
            def __init__(self, wrapped):
                self._wrapped = wrapped

            def __call__(self, result):
                return _TRUSTED_SUITE_RUN(self._wrapped, result)

            def countTestCases(self):
                return _TRUSTED_SUITE_COUNT(self._wrapped)

            def __iter__(self):
                return _TRUSTED_SUITE_ITER(self._wrapped)

        flat_suite = _TRUSTED_TEST_SUITE(flatten_tests(suite))
        for name, method in _TRUSTED_TEXT_TEST_RUNNER_METHODS.items():
            setattr(_TRUSTED_TEXT_TEST_RUNNER, name, method)
        for name, method in _TRUSTED_TEXT_TEST_RESULT_METHODS.items():
            setattr(_TRUSTED_TEXT_TEST_RESULT, name, method)
        result = execute_suite(TrustedSuiteProxy(flat_suite))
    summary = observed
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["tests"] > 0 and not any(
        summary[k] for k in ("failures", "errors", "skipped")
    ) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("regression", "browser"), required=True)
    args = parser.parse_args()
    return run_suite(Path("/workspace"), args.suite)


if __name__ == "__main__":
    raise SystemExit(main())
