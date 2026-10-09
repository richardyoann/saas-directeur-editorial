# Repository Guidelines

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
