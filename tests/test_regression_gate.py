from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest

from scripts.run_regression import run


class RegressionGateTests(unittest.TestCase):
    def evaluate(self, content):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "tests" / "test_gate_fixture.py").write_text(content)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = run(root)
            # unittest caches discovered modules across fixture directories.
            import sys
            sys.modules.pop("test_gate_fixture", None)
            return result

    def test_no_tests_blocks_delivery(self):
        self.assertEqual(self.evaluate(""), 1)

    def test_skipped_test_blocks_delivery(self):
        self.assertEqual(self.evaluate(
            "import unittest\nclass C(unittest.TestCase):\n @unittest.skip('unavailable')\n def test_case(self): pass\n"), 1)

    def test_failed_test_blocks_delivery(self):
        self.assertEqual(self.evaluate(
            "import unittest\nclass C(unittest.TestCase):\n def test_case(self): self.fail('regression')\n"), 1)
