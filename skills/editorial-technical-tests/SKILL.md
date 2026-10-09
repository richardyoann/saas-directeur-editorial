---
name: editorial-technical-tests
description: Tester automatiquement le code Python/FastAPI et les outils de traçabilité du projet avec unittest et les transports HTTPX existants.
metadata:
  version: "1.0.0"
---

# editorial-technical-tests

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Lancer `.venv/bin/python scripts/project.py check TASK_ID` pour exécuter les vérifications prévues par l'outil et journaliser la preuve. Pour une sélection justifiée, exécuter directement `.venv/bin/python -m unittest discover -s tests -v` ou le module concerné, puis consigner le résultat avec `record`. Utiliser `unittest`, `IsolatedAsyncioTestCase`, `httpx.ASGITransport` et `MockTransport` déjà présents ; ne pas installer pytest ou remplacer HTTPX.

Tester des comportements : succès et contrat amont, entrées invalides sans appel amont, configuration manquante, indisponibilité, délais et réponse amont invalide. Restaurer les variables d'environnement et `app.dependency_overrides` après chaque test. Pour la mémoire, vérifier persistance, reprise, intégrité et absence de secrets plutôt que copier la logique interne.

Rapporter commande, code de sortie, cas exécutés et échecs. Un transport simulé prouve le comportement local, pas la disponibilité de Qwen. Étendre la vérification uniquement si les changements ou un échec le justifient.
