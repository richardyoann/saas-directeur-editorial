---
name: editorial-functional-tests
description: Vérifier les parcours réels du SaaS, le contenu des réponses Qwen et les critères utilisateurs, en distinguant accès réseau et qualité éditoriale.
metadata:
  version: "1.0.0"
---

# editorial-functional-tests

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Définir un scénario utilisateur et ses critères avant l'appel. Pour l'intégration modèle, exécuter `.venv/bin/python scripts/check_llm_integration.py` et journaliser son résultat avec `record` puis, lorsqu'un serveur API est disponible, vérifier le parcours HTTP POST `/ai/generate`. Contrôler HTTP 200, statut, fournisseur, modèle, durée, usage et contenu textuel non vide ; signaler une troncature.

L'URL Windows peut changer : utiliser la configuration disponible sans afficher `.env`. Une interdiction réseau de l'environnement n'est pas une panne démontrée du serveur Windows. Enregistrer le blocage et la commande à exécuter depuis WSL2 autorisé. Les résultats fournis par l'utilisateur sont des preuves `source=user` avec date et limites, jamais des tests agent.

L'intégration technique peut être validée indépendamment de la qualité éditoriale. Évaluer celle-ci avec des critères explicites et conserver les exemples utiles sans données sensibles. Ne pas appliquer de migration ou modifier l'infrastructure pour contourner un blocage.
