"""Browser journeys fail closed: no skipped or missing tests."""
import json
from pathlib import Path
import sys
import unittest


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    suite = unittest.TestLoader().discover(str(root / "browser_checks"), pattern="test_studio_browser.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({
        "tests": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped)
    }))
    return 0 if result.wasSuccessful() and result.testsRun > 0 and not result.skipped else 1


if __name__ == "__main__":
    sys.exit(main())
