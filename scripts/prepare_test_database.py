"""Prepare trace tables only on the explicitly named disposable test DB."""
import os
from pathlib import Path
from urllib.parse import urlsplit


def prepare():
    migration = Path("migrations/001_traceability.sql")
    if not migration.is_file():
        return
    url = os.environ["TRACE_TEST_DATABASE_URL"]
    parsed = urlsplit(url)
    if (parsed.scheme not in {"postgres", "postgresql"} or
        parsed.hostname not in {"localhost", "127.0.0.1"} or
        parsed.username != "po_test" or parsed.path != "/po_test" or
        parsed.password != "ephemeral_ci_only" or parsed.query or parsed.fragment):
        raise ValueError("Refusing migration outside disposable CI database")
    import psycopg
    with psycopg.connect(url) as connection:
        connection.execute(migration.read_text())


if __name__ == "__main__":
    prepare()
