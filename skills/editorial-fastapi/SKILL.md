---
name: editorial-fastapi
description: Développer les routes et le client HTTP FastAPI du SaaS, notamment le contrat llama.cpp, en préservant les erreurs contrôlées et la configuration existante.
metadata:
  version: "1.0.0"
---

# editorial-fastapi

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Examiner `apps/api/main.py`, `requirements.txt`, `.env.example` et les tests pertinents. Conserver quatre espaces, `snake_case`, modèles Pydantic `PascalCase` et séparation des imports. Valider les entrées avec Pydantic, gérer le cycle de vie du client HTTP et définir des délais explicites.

Maintenir le contrat `/ai/generate` : réponse non vide, fournisseur, modèle, durée et usage lorsqu'ils existent. Les tests actuels distinguent saisie invalide 422, configuration invalide 503, indisponibilité/réponse amont invalide 502 et timeout 504. Préserver ou expliquer toute modification de ce contrat.

Injecter le client via `get_llm_client` pour les tests. Ne pas révéler détails privés amont ni secrets. Ne pas réinstaller FastAPI/HTTPX opérationnels et ne pas changer `.env`, Compose ou l'infrastructure sans confirmation lorsque leur remplacement ou modification est nécessaire. Ajouter une validation ciblée puis transmettre les fichiers et résultats à la revue.
