---
name: editorial-memory
description: Tenir la mémoire persistante des missions, actions, décisions et interactions du projet, et reprendre le contexte sans confondre sources ou statuts.
metadata:
  version: "1.0.0"
---

# editorial-memory

## Reprise et traçabilité

Lire `AGENTS.md`, `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant la mission. Utiliser `.venv/bin/python scripts/project.py` : `start TASK_ID --objective "Objectif"`, `record TASK_ID --kind decision --actor ROLE --summary "Motif" --source agent`, `status TASK_ID`, `check TASK_ID`, `context --task TASK_ID` et `manifest TASK_ID`. Consulter `--help` avant les options avancées. Les types `interaction`, `action`, `evidence` et `handoff` complètent `decision`.
Relier les actions, décisions, interactions et preuves à la mission. Pour les preuves, utiliser `--data-json` avec `gate` et `outcome` ; attribuer `--source user` aux preuves utilisateur, sans prétendre les avoir vérifiées indépendamment. Les vérifications exécutées via `check` sont journalisées par l'outil ; résumer manuellement les autres outils et messages avec `record`. Ne pas prétendre capturer automatiquement toute la conversation. Ne jamais consigner le contenu de `.env` ou des secrets.

## Workflow

Utiliser le journal via `scripts/project.py`, sans remplacer les entrées existantes. Enregistrer le but, le motif des décisions, les alternatives utiles, fichiers concernés, commandes et résultats observés. Résumer les demandes et corrections de l'utilisateur avec leur provenance ; ne pas inventer de transcription complète.

Avant une reprise, consulter `context` et `status`, puis confronter la synthèse aux fichiers et preuves. Mettre `docs/memory/CURRENT.md` et `ETAT_PROJET.md` à jour avec les décisions actives et la prochaine action. Garder les événements historiques lorsqu'une conclusion est corrigée.

Les tests exécutés par l'utilisateur portent `source=user`; ne pas les présenter comme exécutés par l'agent. Exclure secrets, données personnelles inutiles et sorties brutes sensibles. La mémoire de développement locale ne constitue pas l'historisation PostgreSQL des traitements métier.
