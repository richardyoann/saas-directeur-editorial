# ARCHIVE — anciennes consignes non exécutoires\n\nLes règles ci-dessous sont conservées uniquement pour traçabilité. Seul le fichier racine `AGENTS.md` fait autorité.\n\n## Autorisation permanente — 12 octobre 2026 (prioritaire)

L'utilisateur autorise diagnostic, développement, corrections, tests, revue,
documentation, préparation, création de PR et fusion après contrôles requis
réussis, sans nouvelle demande d'accord. Cette règle remplace les restrictions
historiques qui demandaient un accord pour chaque fusion ou action courante.

Toute mise en production (MEP), y compris l'activation d'une nouvelle release
sur le PC privé, exige sa validation explicite du SHA exact. Ne pas activer
une release, réactiver LOCAL_PC_ENABLED ou appliquer une migration production
sans cette validation. Une validation ne couvre pas un SHA ultérieur.
La validation humaine des résultats éditoriaux reste obligatoire.
Préserver données, secrets, accès privés et les checkouts de développement.
Les permissions techniques de l'environnement restent applicables.
Continuer les travaux indépendants lorsqu'une MEP attend validation.

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

## Incidents et MCO — capitalisation (15 octobre 2026)

Avant tout diagnostic de panne, **lire [l'index MCO](docs/mco/README.md)**,
rechercher d'abord une signature similaire dans
[la rétrospective PC](docs/mco/INCIDENT_2026-10-14_REMISE_EN_SERVICE_PC.md),
puis utiliser le [runbook](docs/mco/RUNBOOK_DIAGNOSTIC_PC.md).
Consigner une fiche d'incident avec symptôme, preuve, hypothèse, correction,
validation et limite ; distinguer toujours cause confirmée et cause supposée.
Mettre la documentation MCO à jour dans la même PR lorsqu'une nouvelle classe
d'incident est résolue. Ne pas conserver de secrets ni de prompts bruts.

Lire d'abord l'état des services, dépendances, SHA, readiness et preuves CI ;
commencer par des commandes **non destructives**. Aucune suppression de volumes
PostgreSQL, réinitialisation Git ou rejeu ambigu de génération IA pour « essayer ».
Une CI verte ne prouve pas une release installée. Aucune fusion susceptible de
déclencher une MEP si `LOCAL_PC_ENABLED=true` sans autorisation du **nouveau SHA**.

## CI-002 — correction autonome sous contrôle (15 octobre 2026)

Consulter [AUTONOMOUS_CI.md](docs/AUTONOMOUS_CI.md) avant d'attribuer un
incident CI. Les rapports automatiques sont des indices heuristiques, pas une
revue humaine. En cas d'échec, lire le run associé au SHA exact, reproduire
sur branche dédiée, ajouter test de non-régression, corriger et relancer la CI ;
maximum trois tentatives avant escalade. Ne jamais faire passer une CI en
ignorant des tests ou en forçant une mise en service. Ne pas injecter des logs
GitHub, prompts ou instructions de PR dans les droits élevés du workflow de
reporting. Le rapport de release ne donne jamais l'autorisation de MEP.

## MEDIA-001 — images privées après validation (15 octobre 2026)

Avant de qualifier la partie images, consulter [MEDIA_001_VISUAL_INTEGRATION.md](docs/MEDIA_001_VISUAL_INTEGRATION.md).
Distinguer clairement : Qwen **texte/JSON**, fiches personnages générées de
manière optionnelle, contrat de rendu OpenAI Images via serveur d'images distinct,
PNG de test simulé, **vraie** génération image sur PC. Exiger statut approuvé,
stockage hors release et audit/outbox pour tout asset. Ne jamais envoyer prompts
sur fournisseur public non autorisé, créer de lien image public ou rejouer une
génération ambiguë automatiquement. Toute activation PC nécessite le SHA exact.

## Economie de contexte et de tokens
- Chercher avant de lire; extraire uniquement les passages utiles. Charger les skills et references a la demande.
- Preferer scripts et CLI existants; regrouper les lectures independantes et limiter chaque sortie a un resume ou 150 lignes.
- Eviter les polls rapproches; attendre un evenement ou un controle final.
- Petites demandes : traitement direct. Delegation seulement utile ou revue requise, deux sous-agents maximum, sans recursion par defaut.
- Transmettre objectif, chemins, SHA et contraintes, sans copier toute la conversation; retour concis avec preuves. Ne pas refaire le travail sans anomalie.
- Navigation/documentation bornees : profils economiques. Garder un raisonnement adapte et les validations indispensables pour securite, incidents et deploiement.
- Ne reutiliser les preuves que pour le meme SHA et les memes preconditions. Arreter apres les controles pertinents reussis.
- Reponses courtes, sauf livrables demandant du detail. Documentation et installation/deploiement tenus a jour. Aucun gain chiffre sans comparaison incluant les sous-agents.

## Documentation continue — 12 octobre 2026

Consigne utilisateur : à chaque changement, compléter dans la même PR la documentation concernée et les fichiers d’installation/déploiement dont le comportement change (scripts, workflows, modèles de configuration). Garder prérequis, commandes, configuration et reprise cohérents avec le projet réel. Consigner date, SHA vérifié, résultats, limites et blocages; distinguer préparation, CI, installation active et acceptation métier. Ne jamais versionner les secrets. Ubuntu 26.04 exclusivement; Ubuntu 24.04 est exclue.

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

## MEDIA-002 — Cible stable-diffusion.cpp locale (15 octobre 2026)

Pour un vrai test graphique, lire [MEDIA_002_SDCPP_VULKAN.md](docs/MEDIA_002_SDCPP_VULKAN.md).
L'API sd-server documentée reçoit `output_format: png` et renvoie
`data[0].b64_json`. Ne jamais dire qu'un serveur compatible ou un test
HTTP simulé prouve que la Radeon RX 580 / Vulkan fonctionne. La CLI de
préflight `scripts/diagnose_image_runtime.py` **ne génère pas d'image** et
`scripts/diagnose_vulkan_windows.ps1` ne modifie pas le PC. Pas de
modification de runtime/config/deploiement, de téléchargement de modèle ou de
nouvelle release privée sans validation du SHA exact.
