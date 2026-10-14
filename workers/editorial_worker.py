"""Opt-in durable editorial worker. PostgreSQL is the queue source of truth.

Runs only when explicitly configured and started as a separate private service.
No automatic retries of ambiguous LLM calls: interrupted jobs require
reconciliation by an operator; queued jobs survive restarts.
"""
import argparse
import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID

import httpx
from dotenv import load_dotenv

from editorial.service import run_steps
from editorial.store import PostgresStore

LOG = logging.getLogger("editorial.worker")


def configuration():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if os.getenv("EDITORIAL_ASYNC_ENABLED", "").lower() != "true":
        raise RuntimeError("Worker disabled: enable EDITORIAL_ASYNC_ENABLED=true only after configuring the service")
    url = os.getenv("PO_DATABASE_URL", "")
    base_url = os.getenv("LLM_BASE_URL", "")
    token = os.getenv("EDITORIAL_API_TOKEN", "")
    if not url or not base_url or len(token) < 32:
        raise RuntimeError("Worker DB, model endpoint or service credentials missing")
    try:
        tenant = UUID(os.environ["EDITORIAL_TENANT_ID"])
        actor = UUID(os.environ["EDITORIAL_ACTOR_ID"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Worker identity not configured") from exc
    return url, base_url, tenant, actor


async def once(store, tenant, actor, client, base_url):
    """Claim one job; never retry claims which are already running."""
    run = await asyncio.to_thread(store.claim_queued, tenant, actor)
    if run is None:
        return False
    # The worker only processes its own configured private tenant.
    LOG.info("Claimed editorial job id=%s", run["id"])
    try:
        owner_actor = UUID(run["run_owner_actor"])
        await run_steps(store, tenant, owner_actor, run, client, base_url)
    except Exception:
        # Do not emit exception text: provider errors can contain raw prompts.
        # Reconciliation (existing /reconcile route) records the failure
        # after the conservative 10-minute threshold; never auto-replay.
        LOG.error("Unexpected worker failure id=%s; requires reconciliation", run["id"])
    return True


async def serve(store, tenant, actor, base_url, *, single=False, interval=1.0):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=5.0), trust_env=False,
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=2)
    ) as client:
        while True:
            claimed = await once(store, tenant, actor, client, base_url)
            if single:
                return claimed
            if not claimed:
                await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Claim at most one queued run and exit")
    options = parser.parse_args()
    try:
        url, base_url, tenant, actor = configuration()
    except RuntimeError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = PostgresStore(url)
    asyncio.run(serve(store, tenant, actor, base_url, single=options.once))


if __name__ == "__main__":
    main()
