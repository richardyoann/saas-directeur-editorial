"""Per-tenant PostgreSQL advisory lock as an opt-in worker liveness guard.

The persistent session lock is owned by the worker process. It is lost if
that worker process dies or PostgreSQL disconnects. This protects the
single-tenant private MVP against accepting new jobs with no consumer.
It is not a distributed heartbeat/latency guarantee.
"""
import hashlib
from contextlib import contextmanager

import psycopg


class WorkerOffline(Exception):
    """No registered consumer for the requested tenant."""


class WorkerAlreadyRunning(Exception):
    """At most one model-consuming worker per tenant in the private MVP."""


def worker_lock_id(tenant):
    # Stable signed bigint on any machine/Python version; never use hash().
    digest = hashlib.sha256(b"editorial-worker-v1:" + tenant.bytes).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@contextmanager
def registered_worker(database_url, tenant):
    """Hold a session-level advisory lock for the entire worker lifetime.

    Autocommit prevents a long-running idle-in-transaction session.
    Closing the connection releases the lock even after unexpected exits.
    """
    with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as conn:
        key = worker_lock_id(tenant)
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:
            raise WorkerAlreadyRunning("Un worker est déjà enregistré pour ce tenant.")
        try:
            yield
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))


def worker_online(database_url, tenant):
    """Read-only availability probe; releases the test lock on disconnect."""
    with psycopg.connect(database_url, autocommit=True, connect_timeout=5) as conn:
        key = worker_lock_id(tenant)
        acquired = conn.execute(
            "SELECT pg_try_advisory_lock(%s)", (key,)
        ).fetchone()[0]
        if acquired:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
        return not acquired
