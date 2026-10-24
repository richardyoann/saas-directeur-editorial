"""Trusted unittest collector for the host-supervised CI.

This file must be installed in /trusted from the independently reviewed
controller checkout. Invoke it with Python -I so candidate sitecustomize and
PYTHONPATH cannot replace the runner before test discovery. Candidate tests
still execute as untrusted code inside the isolated Docker container.
"""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import unittest


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
    suite = unittest.TestSuite()
    targets = (
        (("tests", "test_*.py"), ("pilotage", "test_*.py"))
        if suite_name == "regression" else
        (("browser_checks", "test_studio_browser.py"),)
    )
    for directory, pattern in targets:
        if (root / directory).is_dir():
            suite.addTests(unittest.TestLoader().discover(
                str(root / directory), pattern=pattern))
    # Keep candidate stdout separate from the one authoritative JSON result.
    with redirect_stdout(sys.stderr):
        result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
    summary = {
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("regression", "browser"), required=True)
    args = parser.parse_args()
    return run_suite(Path("/workspace"), args.suite)


if __name__ == "__main__":
    raise SystemExit(main())
