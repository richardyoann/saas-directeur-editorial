---
name: editorial-versioning
description: Versionner les agents, skills et livrables du projet avec preuves de fichiers, et préparer les changements Git lorsque les métadonnées sont disponibles.
metadata:
  version: "1.0.0"
---

# editorial-versioning

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Examiner `git status` et les différences avant toute action Git ; préserver les modifications préexistantes. Les skills canoniques sont `skills/<nom>/SKILL.md` avec `metadata.version`, les agents `agents/<nom>.toml`. Valider les frontmatters et parser les TOML avant de produire un manifeste.

Créer le manifeste de fichiers avec `scripts/project.py manifest` ; exclure `.env`, secrets, poids, médias et environnements locaux. Un manifeste haché décrit l'état des fichiers, ce n'est pas un commit Git. Si `.git` est masqué ou indisponible, consigner le blocage et ne pas inventer une branche, un hash Git ou un historique.

Lorsque Git est accessible et l'action autorisée, préparer des changements ciblés et un sujet impératif concis. Décrire les comportements, preuves de tests et risques dans la proposition de revue. Ne pas écraser des fichiers de configuration existants ni effectuer push, reset ou suppressions sans autorisation correspondante.
