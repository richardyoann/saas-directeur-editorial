# Arvor — Directeur éditorial privé

Studio éditorial privé pour structurer des histoires et leurs scènes, valider les propositions IA, générer des images locales et préparer des exports vidéo.

> **État :** MVP privé mono-identité. Les fonctions multi-tenant/RBAC, abonnements, publication CMS et exposition publique ne sont pas implémentées comme produit SaaS.

## Architecture

- `apps/api/` : API FastAPI sécurisée, façade navigateur `/studio`, génération Qwen via llama.cpp.
- `apps/web/` : interface HTML/CSS/JavaScript native, sans compilation.
- `editorial/` : workflows, validation humaine, PostgreSQL `po_*`, audit/outbox.
- `workers/` : worker PostgreSQL optionnel (aucun rejeu automatique ambigu).
- `infrastructure/` et `production/` : stockage média privé (disque/MinIO), images sd.cpp, voix Piper, export FFmpeg.
- `scripts/` : diagnostics, recettes et livraison.
- `compose.yml` : PostgreSQL, MinIO épinglé, Redis optionnel et non utilisé par la file éditoriale.

## Installation privée

Prérequis : Python 3.12 ou 3.14, PostgreSQL 16, accès à un LLM llama.cpp local, et WSL Ubuntu 26.04 sur PC.

1. `python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`.
2. `cp .env.example .env` puis configurer sans exposer les secrets : `PO_DATABASE_URL`, `LLM_BASE_URL`, `EDITORIAL_API_TOKEN`, `EDITORIAL_WEB_PASSWORD`, `EDITORIAL_TENANT_ID`, `EDITORIAL_ACTOR_ID`. Pour la chaîne image/voix/vidéo : `IMAGE_BASE_URL`, `ARVOR_PIPER_MODEL` (et `ARVOR_PIPER_BIN`, `ARVOR_FFMPEG_BIN` si hors `PATH`), voir `.env.example`.
3. `docker compose up -d postgres minio`. Redis n'est pas requis ; pour l'activer explicitement : `docker compose --profile optional-redis up -d redis`.
4. Utiliser une base déjà migrée, ou le runbook de migration isolée en environnement de test ; **ne pas migrer la base métier automatiquement**.
5. `.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --workers 1`.
6. Vérifier `/health`, `/ready`, puis `http://127.0.0.1:8000/studio`.

Ne jamais exposer directement le serveur HTTP sur `0.0.0.0`. Pour un accès mobile privé, consulter `docs/MOBILE_PRIVATE_ACCESS.md`.

## Paramètres de sécurité

- `EDITORIAL_ENABLE_API_DOCS=false` (défaut). Activer seulement pour le développement local de confiance.
- `EDITORIAL_GITHUB_REPOSITORY=owner/repository` et `EDITORIAL_GITHUB_READ_TOKEN` pour le cockpit GitHub; lecture seule, jeton côté serveur, pas de déclenchement de livraison depuis Studio.
- `EDITORIAL_ASYNC_ENABLED=false` (défaut) ; activer uniquement après installation et recette du worker.
- Les sessions Studio sont en mémoire : **un seul worker Uvicorn** tant qu'un backend partagé n'est pas disponible.
- Les volumes PostgreSQL et MinIO ne doivent jamais être supprimés lors d'un correctif exploratoire ; ne pas utiliser `docker compose down -v`.
- Si la version MinIO déjà installée diffère de celle déclarée, vérifier la compatibilité et sauvegarder le stockage avant tout `pull` / recréation du conteneur.

## QA / CI

```bash
.venv/bin/python scripts/run_regression.py
.venv/bin/python scripts/diagnose_project.py
```

La régression complète s'effectue sur base **jetable**, via le workflow GitHub `Full regression`, matrice Python 3.12/3.14. L'audit des dépendances Python, les parcours navigateur et la livraison PC sont distincts.

Une CI verte ne prouve pas une livraison locale : celle-ci exige validation du SHA exact et vérification de `last_delivery.json`, `/ready` et `/studio`.

## Documentation utile

- `docs/ARVOR_MULTI_AGENT_PRODUCTION_2026-10-17.md` : équipe IA, critique stricte de préproduction, contrôle MP4 (code en PR, non livré sur PC).
- `docs/mco/README.md` : incidents, diagnostic et capitalisation MCO.
- `docs/mco/RUNBOOK_DIAGNOSTIC_PC.md` : reprise privée Windows/WSL.
- `docs/EDITORIAL_WORKFLOW.md` : modèle et validation éditoriale.
- `docs/MOBILE_PRIVATE_ACCESS.md` : proxy privé et sécurité.
- `docs/QA_LOT1_2026-10-15.md` : limites des campagnes QA.
- `docs/mco/README_LEGACY_20261016.md` : historique détaillé du README.
- `AGENTS.md` : instructions normatives des agents.
