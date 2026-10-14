"""Safety gates for the strictly disposable PostgreSQL query benchmark."""
import os
import unittest
from unittest.mock import patch

from scripts.benchmark_editorial_sql import benchmark


class BenchmarkSafetyTests(unittest.TestCase):
    def test_missing_authorization_and_invalid_population_refused(self):
        with patch.dict(os.environ, {"PO_ALLOW_TEST_MIGRATION": ""}):
            with self.assertRaises(ValueError):
                benchmark("postgresql://test", 300)
        with patch.dict(os.environ, {"PO_ALLOW_TEST_MIGRATION": "yes"}):
            for count in (0, 299, 5001):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    benchmark("postgresql://test", count)

    def test_application_database_url_is_never_a_benchmark_target(self):
        with patch.dict(os.environ, {"PO_ALLOW_TEST_MIGRATION": "yes",
                                     "PO_DATABASE_URL": "postgresql://app"}):
            with self.assertRaises(ValueError):
                benchmark("postgresql://app", 300)


if __name__ == "__main__":
    unittest.main()
