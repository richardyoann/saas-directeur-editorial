"""Run every historical unittest suite; missing/skipped tests block delivery."""
import json
from pathlib import Path
import sys
import unittest


def run(root: Path) -> int:
    suite = unittest.TestSuite()
    for directory in ("tests", "pilotage"):
        if (root / directory).is_dir():
            suite.addTests(unittest.TestLoader().discover(str(root / directory), pattern="test_*.py"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {"tests": result.testsRun, "failures": len(result.failures),
               "errors": len(result.errors), "skipped": len(result.skipped)}
    print(json.dumps(summary, sort_keys=True))
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped else 1


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    raise SystemExit(run(root))
