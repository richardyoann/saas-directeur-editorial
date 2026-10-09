---
name: editorial-postgres-design
description: Concevoir la traçabilité PostgreSQL des prompts, traitements, scénarios, scènes et résultats du SaaS ; préparer un schéma sans appliquer de migration.
metadata:
  version: "1.0.0"
---

# editorial-postgres-design

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Séparer la mémoire de développement locale des données métier. Concevoir des identifiants stables et relations explicites entre projet, prompt/version, traitement, scénario/version, scène/version et résultat. Conserver entrées nécessaires, statut, origine, agent/skill/version, modèle, paramètres, durée, usage et références des artefacts ; éviter les secrets et définir la rétention.

Décrire les décisions dans un document de conception et relier chaque traitement aux versions exactes de ses prompts et skills. Prévoir des états d'échec, reprises idempotentes et transactions cohérentes. Analyser besoins de recherche et accès avant de proposer indexes ou contraintes.

Examiner les dépendances et l'existant avant de choisir ORM et outil de migrations. Produire une migration reviewable uniquement si demandée ; aucune migration appliquée, connexion mutante, création de service ou modification Compose sans confirmation. Les scripts non appliqués et architecture proposée restent marqués prévus ou développés, jamais déployés.
