---
name: editorial-documentation
description: Documenter les changements techniques, preuves et décisions dans ETAT_PROJET et la mémoire du SaaS sans transformer des intentions en fonctionnalités livrées.
metadata:
  version: "1.0.0"
---

# editorial-documentation

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Lire les fichiers modifiés et les preuves avant de modifier README, `ETAT_PROJET.md` ou les documents de conception. Indiquer composants concernés, comportement résultant, commandes de validation, résultats, origine des preuves, limitations et prochaine étape.

Utiliser les statuts développé, testé automatiquement, testé réellement et prévu. Conserver l'attribution et la date des tests utilisateur ; ne pas présenter une validation éditoriale comme acquise sur la seule base d'une réponse non vide. Une migration rédigée mais non appliquée reste explicitement non appliquée.

Mettre la synthèse persistante à jour après la mission sans effacer l'historique. Ne pas modifier `AGENTS.md` racine dans ce workflow. Retirer les informations obsolètes des documents concernés en conservant les décisions dans le journal. Éviter les secrets, dumps de configuration et journaux excessifs.
