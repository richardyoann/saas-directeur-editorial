"""Measure editorial SQL plans on TEMPORARY synthetic PostgreSQL tables only.

No migration, no index or data change to the application's po_entity table.
The test connection MUST be a separately authorized disposable database.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

RUN_SQL = (
    "SELECT entity_id,content FROM pg_temp.po_entity WHERE tenant_id=%s "
    "AND kind='treatment' AND content->>'type'='editorial_run' AND NOT deleted "
    "ORDER BY content->>'created_at' DESC, entity_id DESC LIMIT 21"
)
HISTORY_SQL = (
    "SELECT content FROM pg_temp.po_entity WHERE tenant_id=%s AND kind='result' "
    "AND content->>'run_id'=%s AND content->>'type'='editorial_step_snapshot' "
    "AND NOT deleted ORDER BY (content->>'order')::integer"
)
REVIEWS_SQL = (
    "SELECT content FROM pg_temp.po_entity WHERE tenant_id=%s AND kind='result' "
    "AND content->>'run_id'=%s AND content->>'type'='editorial_review' AND NOT deleted "
    "AND (%s::integer IS NULL OR (content->>'revision')::integer < %s) "
    "ORDER BY (content->>'revision')::integer DESC LIMIT 21"
)
INDEXES = [
    ("runs", """CREATE INDEX benchmark_runs_idx ON pg_temp.po_entity
        (tenant_id, (content->>'created_at') DESC, entity_id DESC)
        WHERE kind='treatment' AND content->>'type'='editorial_run' AND NOT deleted"""),
    ("snapshots", """CREATE INDEX benchmark_snapshots_idx ON pg_temp.po_entity
        (tenant_id, (content->>'run_id'), ((content->>'order')::integer))
        WHERE kind='result' AND content->>'type'='editorial_step_snapshot' AND NOT deleted"""),
    ("reviews", """CREATE INDEX benchmark_reviews_idx ON pg_temp.po_entity
        (tenant_id, (content->>'run_id'), ((content->>'revision')::integer) DESC)
        WHERE kind='result' AND content->>'type'='editorial_review' AND NOT deleted"""),
]


def _explain(conn, query, params):
    item = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params).fetchone()[0]
    plan = json.loads(item)[0] if isinstance(item, str) else item[0]
    types = []
    def nodes(node):
        types.append(node.get("Node Type", "?"))
        for child in node.get("Plans", []):
            nodes(child)
    nodes(plan["Plan"])
    return {"milliseconds": round(plan["Execution Time"], 4),
            "plan": types, "returned_rows": plan["Plan"]["Actual Rows"]}


def _copy_demo(conn, count):
    tenant, other = uuid4(), uuid4()
    chosen = None
    at = datetime(2026, 10, 14, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        with cur.copy(
            "COPY pg_temp.po_entity (tenant_id,kind,entity_id,version,content,deleted) FROM STDIN"
        ) as sink:
            for index in range(count):
                owner = tenant if index % 4 else other
                run_id = uuid4()
                if chosen is None and owner == tenant:
                    chosen = run_id
                timestamp = (at + timedelta(seconds=index)).isoformat()
                payload = {"type": "editorial_run", "created_at": timestamp,
                           "brief": {"topic": "Légende " + str(index)},
                           "status": "waiting_validation"}
                sink.write_row((owner, "treatment", run_id, 1, Jsonb(payload), False))
                for order in (0, 1):
                    result = {"type": "editorial_step_snapshot", "run_id": str(run_id),
                              "order": order, "parsed": {"test": "contenu"}}
                    sink.write_row((owner, "result", uuid4(), 1, Jsonb(result), False))
                review = {"type": "editorial_review", "run_id": str(run_id),
                          "revision": 1, "action": "accept"}
                sink.write_row((owner, "result", uuid4(), 1, Jsonb(review), False))
    return tenant, chosen


def benchmark(database_url, count=1200):
    if not 300 <= count <= 5000:
        raise ValueError("300 to 5000 synthetic runs required")
    if not database_url or not os.getenv("PO_ALLOW_TEST_MIGRATION") == "yes":
        raise ValueError("Disposable test database authorization required")
    if os.getenv("PO_DATABASE_URL") and database_url == os.getenv("PO_DATABASE_URL"):
        raise ValueError("Refusing to benchmark the application database")
    with psycopg.connect(database_url, connect_timeout=5, autocommit=True) as conn:
        # Shadow the permanent table; all generated records and indexes vanish
        # when this connection closes.
        conn.execute("CREATE TEMP TABLE po_entity (LIKE public.po_entity INCLUDING ALL) "
                     "ON COMMIT PRESERVE ROWS")
        tenant, run_id = _copy_demo(conn, count)
        conn.execute("ANALYZE pg_temp.po_entity")
        queries = {
            "list": (RUN_SQL, (tenant,)),
            "history": (HISTORY_SQL, (tenant, str(run_id))),
            "reviews": (REVIEWS_SQL, (tenant, str(run_id), None, None)),
        }
        before = {name: _explain(conn, statement, params)
                  for name, (statement, params) in queries.items()}
        checksums = {name: [str(row) for row in conn.execute(statement, params).fetchall()]
                     for name, (statement, params) in queries.items()}
        for _, create in INDEXES:
            conn.execute(create)
        conn.execute("ANALYZE pg_temp.po_entity")
        after = {name: _explain(conn, statement, params)
                 for name, (statement, params) in queries.items()}
        for name, (statement, params) in queries.items():
            result = [str(row) for row in conn.execute(statement, params).fetchall()]
            if result != checksums[name]:
                raise RuntimeError("Index changed results: " + name)
        return {"synthetic_runs": count, "synthetic_rows": count*4,
                "queries": {name: {"before": before[name], "with_indexes": after[name]}
                            for name in queries}, "persistent_ddl": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1200)
    parser.add_argument("--disposable", action="store_true",
                        help="Required confirmation: an isolated test DB, never real user data")
    args = parser.parse_args()
    if not args.disposable:
        parser.error("Explicit --disposable confirmation required")
    url = os.getenv("PO_TEST_DATABASE_URL")
    result = benchmark(url, args.rows)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
