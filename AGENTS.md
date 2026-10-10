# Repository Guidelines

## Current traceability workflow — 10 October 2026

This section supersedes initial-state statements below about missing tests and
dependencies. Read `docs/TRACEABILITY.md` and `ETAT_PROJET.md` on resumption.
Use `requirements.txt` and `python -m unittest discover -s tests -v`; distinguish
Linux-dependent legacy failures from the portable POC. Never report skipped tests
or simulated Slack/model calls as successful live integrations.

For work items and persisted business events, write domain mutation, audit and
outbox in the same PostgreSQL transaction using `traceability.store.emit`.
Keep stable item/parent IDs, UUID event/correlation and unique source keys.
Allow only typed metadata from `traceability.events.safe_data`. Do not submit
prompts, outputs, titles, secrets, headers or raw exception messages to Slack/audit.
Authenticated trace endpoints and signed PR webhook are in `traceability/api.py`.
Never resend uncertain Slack deliveries automatically; use verified reconciliation.

Slack target: workspace T0C7ZUAM4DR, channel C0C883XR3DF, List F0C83UZ4XHB.
List write access is currently refused; channel messages work. Trace operational
changes and every created PR in that channel, with real evidence and blockers.
Do not invent List items or claim automated synchronization is active.

Do not assume WSL access. A Windows snapshot may not include unpushed local work.
Ask before destructive operations or public publication. Apply migrations only
to explicitly approved targets; the approval for trace_test is not production
approval. Preserve `.env`, existing Compose/services, user changes and source files.

## Project Structure & Module Organization

- `apps/api/main.py` contains the FastAPI application, request schema, health endpoint, and llama.cpp generation proxy.
- `apps/web/` is reserved for the frontend; it currently contains no implementation.
- `workers/` and `workflows/` contain Python package placeholders for background processing and orchestration.
- `tests/`, `docs/`, `prompts/`, and `scripts/` are currently empty; place corresponding additions in these directories.
- `infrastructure/` groups service directories. The root `compose.yml` defines PostgreSQL, Redis, and MinIO.
- `media/{input,generated,working,export}/` and `models/` hold local artifacts excluded from version control.

## Build, Test, and Development Commands

No dependency manifest, build script, or test runner configuration is currently provided. With FastAPI, HTTPX, and Uvicorn installed in your Python environment:

- `source .venv/bin/activate` activates the local virtual environment, if present.
- `docker compose up -d` starts PostgreSQL, Redis, and MinIO.
- `docker compose down` stops those services; avoid `-v` unless intentionally deleting persistent data.
- `uvicorn apps.api.main:app --reload --env-file .env` runs the API locally; loading the environment file requires `python-dotenv`.
- `curl http://127.0.0.1:8000/health` checks API availability.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for Python functions and variables, and `PascalCase` for Pydantic models. Follow the existing separation of standard-library and third-party imports. Define input constraints with Pydantic fields and map upstream failures to explicit HTTP responses. No formatter or linter is configured; keep edits consistent with surrounding code.

## Testing Guidelines

No tests, testing framework, or coverage threshold are established. For new API tests, use `tests/test_*.py` and descriptive `test_*` functions. Pytest is a suggested choice; once installed and tests exist, run `python -m pytest`. Cover request validation, missing configuration, upstream timeouts, HTTP failures, and malformed responses. Mock upstream HTTP calls to avoid requiring a live model server.

## Commit & Pull Request Guidelines

Git history is unavailable in this workspace, so existing commit conventions cannot be verified. Use concise, imperative subjects such as `Add generation timeout tests`. Pull requests should explain the change, link relevant issues, and report validation commands and results. Include screenshots when adding frontend behavior.

## Security & Configuration

Copy `.env.example` to `.env` and set `LLM_BASE_URL` for your local model server. Keep secrets, model weights, and generated media out of commits. Compose credentials are development defaults; replace them before shared deployment and preserve localhost port bindings for local use.
