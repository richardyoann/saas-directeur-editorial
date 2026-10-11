# Repository Guidelines

## Pilotage privé — 11 octobre 2026 (prioritaire)

Lire pilotage/GUIDE.md, ETAT_PROJET.md et le Project privé https://github.com/users/richardyoann/projects/3.
Dépôt exclusif : richardyoann/saas-directeur-editorial, ID 1411435489. Préserver la PR brouillon #1 et les modifications WSL.
Epics → Stories → tâches → sous-tâches; IDs stables, dépendances et critères concrets. Agent PO : agents/product_owner.toml.
Calculer l’avancement sur les acceptations de stories, avec preuve revue liée au SHA, date, résultat et type. Ne jamais convertir automatiquement merge, CI verte ou fermeture en acceptation.
Branches feat/ID-description, fix/ID-description, ops/ID-description; commits type(ID): résumé; PR avec critères, preuves, risques et reprise.
Tester sous Linux les tests historiques et pilotage/test_*.py. Les tests PostgreSQL nécessitent une cible dédiée; ne pas présenter un skip comme réussite.
Mutations métier : tenant/acteur issus de l’authentification, CRUD + audit + outbox dans la même transaction. pilotage.audit fournit la bibliothèque; aucune route métier production connectée n’est annoncée.
Slack : T0C7ZUAM4DR/C0C883XR3DF. Compteurs et IDs seulement, jamais prompts, outputs, titres métier, secrets ou exceptions brutes. Digest borné, anti-doublons, timeout ambigu suspendu pour réconciliation. Le connecteur ne prouve pas un bot runtime disponible.
Le PO périodique compare la dernière synthèse et reste silencieux sans changement utile. Vérifier son premier run avant de le dire opérationnel.
Garder Project/dépôt privés. Aucun merge, suppression, migration production, élargissement d’accès ou infrastructure existante modifiée sans accord.
Le disque WSL Ubuntu est introuvable dans cette session. Ne pas réinstaller/réinitialiser; identifier une sauvegarde avec l’utilisateur.

## Instructions historiques (constats initiaux à relire à la lumière de la section ci-dessus)

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
