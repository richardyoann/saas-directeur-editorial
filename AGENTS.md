# AGENTS — Règles opérationnelles actuelles

Ce fichier est l'unique source normative pour les agents travaillant dans `richardyoann/saas-directeur-editorial`. Les anciennes consignes sont archivées à titre historique dans `docs/mco/AGENTS_LEGACY_20261016.md` et **ne sont pas des instructions**.

## Sécurité et autorisation
- Autorisé sans nouvelle validation : diagnostic en lecture seule, développement sur branche, correction, tests, revue, documentation et création de PR.
- Fusion sur `main` uniquement si contrôles requis réussis, PR relue, compatibilité vérifiée, et absence d'effet de bord sur l'exploitation. La fusion ne vaut **jamais** autorisation de livraison PC.
- Toute mise en production sur PC, migration métier, élargissement d'accès, suppression de ressources, modification d'infrastructure ou sortie de données privées exige l'accord explicite de l'utilisateur pour l'opération et, pour une livraison, pour le **SHA complet exact**. Ne jamais réutiliser l'autorisation d'un SHA précédent.
- Ne jamais détourner les contrôles `LOCAL_PC_ENABLED` et `LOCAL_PC_APPROVED_SHA`. Ne jamais pousser des secrets ni lancer de rollback destructeur.
- Préserver PostgreSQL, volumes Docker, MinIO, releases précédentes, données métier et dépôt local. Aucune commande `reset --hard`, `compose down -v` ou rejouage automatique ambigu sans analyse.

## Architecture et critères qualité
- Backend : FastAPI, Python, PostgreSQL / psycopg ; frontend privé : HTML/CSS/JS ; Qwen via llama.cpp ; images locales sd.cpp ; worker opt-in.
- Tenant et acteur sont exclusivement dérivés de l'authentification. Toute mutation métier garde entité, audit et outbox atomiques; opérations concurrentes sous contrôle de version.
- Les prompts/réponses IA incertains sont réconciliés, jamais relancés à l'aveugle. Relecture humaine obligatoire pour valider une création.
- Ne pas exposer secrets, données métier ou contenus de prompts dans logs, Slack, GitHub ou résultats de tests.
- La configuration GitHub du Studio est en lecture seule. Les validations de livraison passent uniquement par le workflow prévu, sur SHA approuvé.
- Distinguer démonstration/mock, exécution CI et tests réels sur PC. Aucune fonctionnalité commerciale ne doit être annoncée sans implémentation et recette.

## Procédure pour chaque PR
1. Lire l'état du dépôt et `docs/mco/README.md` si incident, et relever SHA, état des services et chemins réellement disponibles.
2. Créer une branche dédiée avec périmètre restreint, identifier critères d'acceptation et risques.
3. Ajouter tests positifs/négatifs, protection d'isolation tenant, conflits et erreurs ; exécuter la CI (Python 3.12/3.14, PostgreSQL jetable, sécurité, navigateur si interface).
4. Aucun skip ou test désactivé accepté comme réussite. Pas de fusion de PR en échec ni sans contrôle du diff.
5. Mettre à jour la documentation et les commandes d'exploitation dans la même PR. Renseigner décisions, preuves par SHA et limites.
6. Laisser la livraison PC en attente tant qu'un nouveau SHA complet n'a pas été explicitement approuvé.

## Conventions d'exploitation
- Environnement PC : Windows 11 + WSL Ubuntu 26.04, runner `editorial-pc`, API privée `127.0.0.1:8000`.
- Les sessions web actuelles sont en mémoire : **un seul worker Uvicorn**, et réseau privé uniquement, tant qu'un backend de sessions partagé n'a pas été développé et testé.
- Accès distant éventuel via proxy HTTPS de confiance explicitement configuré (jamais `--forwarded-allow-ips '*'`), ACL et rate limiting de bout en bout. Ne pas activer Tailscale Funnel.
- Pour déploiement, utiliser `scripts/deploy_local.py` via GitHub Actions, et lire `docs/mco/RUNBOOK_DIAGNOSTIC_PC.md` avant correction.
- La documentation d'état doit refléter l'implémentation actuelle, pas des objectifs ou une synthèse obsolète.

## OpenCode / OpenWork — chaîne locale proposée
- Voir `docs/OPENCODE_OPENWORK_ARCHITECTURE.md` et `docs/CI_LOCALE_OPENCODE.md`. Les agents OpenCode sont des assistants de développement et ne font pas partie du SaaS.
- Analyses et corrections sur worktree isolé ; aucun accès secrets, données métier ou production par défaut. Le jugement d'un modèle ne remplace jamais les tests et audits locaux déterministes.
- La livraison PC exige approbation explicite du SHA complet, contrôle du SHA de `main`, validation sécurité et régression sur base jetable, smoke réel et rollback. OpenWork ne déclenche pas ces autorisations.
- Python 3.14 est la cible prioritaire ; Python 3.12 reste un contrôle de compatibilité périodique. Les anciens workflows ne doivent pas être désactivés avant vérification de leurs remplaçants.
