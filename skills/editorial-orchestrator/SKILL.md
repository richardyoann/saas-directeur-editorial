---
name: editorial-orchestrator
description: Orchestrer le développement du SaaS Directeur éditorial IA avec délégation, critères de validation et mémoire persistante ; ne pilote pas les agents métier Qwen.
metadata:
  version: "1.0.0"
---

# editorial-orchestrator

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Créer une mission avec objectif, périmètre et critères vérifiables. Consulter la mémoire avant d'attribuer des tâches aux agents dans `agents/` : analyse, développement, tests techniques, tests fonctionnels, documentation, versionnement et revue. Donner à chaque tâche des fichiers distincts lorsqu'elles sont parallèles ; réserver les modifications dépendantes à une séquence.

Recueillir les résultats et preuves, faire revoir les risques puis mettre à jour l'état persistant. Distinguer développé, testé automatiquement, testé réellement et prévu. Un résultat simulé ne valide pas l'accès au serveur Windows. Attribuer une preuve fournie par l'utilisateur à `source=user`.

Demander confirmation avant suppression de données, migration appliquée, modification d'infrastructure ou remplacement de configuration. Un blocage réseau laisse ouvert le critère réel concerné. Pour les étapes, utiliser `status TASK_ID --stage technical_test --outcome passed --summary "Résultat" --source tool` ou les autres étapes autorisées. Les preuves portent `gate=technical_test` ou `gate=functional_test` et `outcome=passed` dans `--data-json`. Un parcours fonctionnel non applicable exige une justification explicite et le statut `not_applicable`, pas une fausse preuve de succès. Clôturer avec `close TASK_ID --summary "Critères satisfaits"` seulement lorsque tous les critères sont satisfaits ; rapporter les blocages et la prochaine action concrète.
