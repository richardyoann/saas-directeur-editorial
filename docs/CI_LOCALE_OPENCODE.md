# CI locale Arvor avec OpenCode

Statut : proposition, non déployée sur PC (18/10/2026).

## Principe

OpenCode et OpenWork aident au développement et au reporting. Les contrôles qui font foi restent des programmes déterministes, lancés sans LLM sur un checkout propre et une base PostgreSQL jetable. Le nouveau script `scripts/local_quality_gate.py` vérifie politique CI, vulnérabilités des dépendances, secrets Git, syntaxe JavaScript/Python, tests unitaires et benchmark SQL.

## Python

Python 3.14 est la cible actuelle. La matrice Python 3.12/3.14 était utile pour vérifier la compatibilité, mais 3.12 peut être réservé à des campagnes manuelles lorsque le seul runtime de livraison est 3.14.

## Livraison

Les workflows `local-delivery.yml` et `chat-approved-delivery.yml` sont proposés sur le runner auto-hébergé `editorial-pc`. Ils exécutent un contrôle qualité indépendant lié au SHA exact, puis `deploy_local.py` réalise l'installation candidate, les probes HTTP et le rollback.

**Important** : les huit anciens workflows sont passés en déclenchement manuel **sur cette branche**, pas encore sur `main`. La baisse des minutes hébergées ne sera effective qu'après fusion et vérification des protections de branche ; les jobs de sécurité ne sont pas supprimés, leur exécution est déplacée vers le gate du runner. Vérifier également les required checks de la protection de `main` et les quotas Actions/Copilot distincts.

## Installation

PowerShell : `scripts/start_opencode_llm_windows.ps1` avec un chemin explicite vers `llama-server.exe`. Modèle suggéré : Qwen3-4B-Instruct-2507 Q4_K_M, alias `arvor-coder-local`, port Windows WSL privé 8083. WSL : `bash scripts/install_opencode_wsl.sh`, puis `opencode`. Le script WSL vérifie une réponse réelle d'appel d'outil avant toute configuration du modèle.

Installer au préalable Python 3.14, Node, ffmpeg, Gitleaks et pip-audit. Préparer une base de test `po_test` séparée de toute base métier. Dans un worktree propre, exporter `PO_TEST_DATABASE_URL`, `TRACE_TEST_DATABASE_URL` et `PO_ALLOW_TEST_MIGRATION=yes`, puis lancer `scripts/local_quality_gate.py` avec `--sha` et `--report`.

Le rapport local d'OpenCode ne remplace jamais une recette du runner. Aucune MEP, migration métier, exposition publique ni modification de secrets sans autorisation explicite.

Voir `docs/OPENCODE_OPENWORK_ARCHITECTURE.md` et `docs/mco/RUNBOOK_DIAGNOSTIC_PC.md`.
