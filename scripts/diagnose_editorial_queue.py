"""Tenant-scoped, read-only snapshot of editorial queue health.

No jobs are claimed, reconciled or retried. Output contains aggregate
counts and ages only; prompts, model responses and DB credentials are omitted.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg
from dotenv import load_dotenv


KNOWN_STATES = (
    "queued", "running", "failed", "waiting_validation",
    "changes_requested", "approved",
)
DEFAULT_QUEUED_SECONDS = 300
DEFAULT_RUNNING_SECONDS = 600

# Project only aggregate metadata, never po_entity.content or brief/prompt.
# The type/tenant predicates follow PostgresStore.list_runs().
QUERY = """
SELECT
    content->>'status' AS run_status,
    COUNT(*) AS run_count,
    MIN(CASE
        WHEN content->>'status' = 'running'
        THEN COALESCE(
            content->'current_step'->>'started_at',
            content->>'claimed_at',
            content->>'updated_at',
            content->>'created_at'
        )
        ELSE content->>'created_at'
    END) AS oldest_activity_at
FROM po_entity
WHERE tenant_id = %s
  AND kind = 'treatment'
  AND NOT deleted
  AND content->>'type' = 'editorial_run'
GROUP BY content->>'status'
"""


def read_rows(database_url, tenant):
    """One PostgreSQL read-only transaction, strictly filtered by tenant."""
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        return conn.execute(QUERY, (tenant,)).fetchall()


def seconds_since(stamp, reference):
    """Return a safe age or None for missing, naive or implausible timestamps."""
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        age = (reference - parsed).total_seconds()
        return int(max(age, 0)) if age >= -60 else None
    except (ValueError, OverflowError):
        return None


def assess(rows, *, reference=None, queued_seconds=DEFAULT_QUEUED_SECONDS,
           running_seconds=DEFAULT_RUNNING_SECONDS):
    """Pure, deterministic interpretation of aggregate SQL results."""
    if queued_seconds <= 0 or running_seconds <= 0:
        raise ValueError("Thresholds must be positive")
    reference = reference or datetime.now(timezone.utc)
    counts = {state: 0 for state in KNOWN_STATES}
    counts["other"] = 0
    oldest = {"queued": None, "running": None}
    alerts = set()
    for raw_state, raw_count, stamp in rows:
        state = raw_state if raw_state in KNOWN_STATES else "other"
        count = int(raw_count)
        if count < 0:
            raise ValueError("Invalid aggregate count")
        counts[state] += count
        if state in oldest and count:
            age = seconds_since(stamp, reference)
            if age is None:
                alerts.add(f"{state}_age_unknown")
            else:
                oldest[state] = max(oldest[state] or 0, age)
                if age >= (queued_seconds if state == "queued" else running_seconds):
                    alerts.add("queued_overdue" if state == "queued" else "running_stale")
    return {
        "status": "alert" if alerts else "ok",
        "total_runs": sum(counts.values()),
        "counts": counts,
        "oldest_age_seconds": oldest,
        "thresholds_seconds": {
            "queued": queued_seconds,
            "running": running_seconds,
        },
        "alerts": sorted(alerts),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queued-seconds", type=int, default=DEFAULT_QUEUED_SECONDS)
    parser.add_argument("--running-seconds", type=int, default=DEFAULT_RUNNING_SECONDS)
    args = parser.parse_args(argv)
    if args.queued_seconds <= 0 or args.running_seconds <= 0:
        parser.error("Thresholds must be positive")
    # The private release has its own .env; process environment takes precedence.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    url = os.getenv("PO_DATABASE_URL")
    try:
        tenant = UUID(os.environ["EDITORIAL_TENANT_ID"])
    except (KeyError, ValueError):
        tenant = None
    if not url or tenant is None:
        print(json.dumps({"status": "unavailable", "reason": "configuration_missing"}))
        return 3
    try:
        result = assess(read_rows(url, tenant),
                        queued_seconds=args.queued_seconds,
                        running_seconds=args.running_seconds)
    except (psycopg.Error, OSError, ValueError, TypeError):
        # Never expose an exception string: it may embed database credentials.
        print(json.dumps({"status": "unavailable", "reason": "database_or_data_error"}))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 2 if result["status"] == "alert" else 0


if __name__ == "__main__":
    sys.exit(main())
