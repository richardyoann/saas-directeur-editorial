# WEB-001 — Contrat de parcours navigateur privé

Issue : #71. Ce document est une spécification d'implémentation, **pas une preuve de fonctionnalité livrée**.

## Parcours MVP
1. Ouvrir l'application privée et vérifier l'identité côté serveur.
2. Consulter les histoires disponibles pour le tenant courant et ouvrir une histoire.
3. Voir scénario, scènes, analyse, storyboard et états de validation.
4. Consulter une exécution et ses deux étapes avec les réponses structurées et versions.
5. Accepter, rejeter ou demander une révision via les routes de décision existantes, avec confirmation explicite.
6. Rafraîchir l'état, puis consulter l'historique paginé et l'audit de la décision.

## Prérequis à inventorier avant développement
- Relever les routes FastAPI réelles, les modèles Pydantic et les erreurs, sans inventer d'endpoint.
- Identifier le mode d'authentification et le stockage du jeton côté serveur : **ne jamais intégrer de secret dans du JavaScript public**.
- Vérifier les contrats d'idempotence, de version, de concurrence et de pagination.
- Conserver les snapshots Qwen, l'attribution du décideur et l'isolation par tenant.

## États d'interface
- Chargement, absence de données, réponse invalide, expiration de session.
- 401 : proposer une nouvelle authentification; 403 : accès refusé; 404 : objet introuvable.
- 409 : conflit ou version obsolète, recharger sans réémettre la décision.
- 422 : afficher une erreur métier compréhensible sans journaliser de prompt.
- Révision : avertir que l'analyse modifiée rend le storyboard précédent obsolète.
- Aucun résultat IA n'est approuvé automatiquement.

## Tests et critères de livraison
- Tests d'affichage et de navigation clavier, mobile et PC.
- Tests d'isolation multi-tenant, de session, de décisions concurrentes et de rejouabilité.
- Tests PostgreSQL isolés et intégration avec Qwen réel avant qualification finale.
- Preuve datée : SHA, commande, résultats, type de test et critères couverts.
- Revue indépendante, CI complète sans skip, documentation MCO et retour arrière.
- Développement, tests et PR autorisés; **activation de la release sur le PC uniquement après validation humaine du SHA exact**.

## Ordre de réalisation
A. Inventaire des contrats API et choix d'un rendu privé compatible avec l'architecture existante.
B. Liste/détail des histoires et exécutions en lecture seule.
C. Décisions de revue et historique.
D. Tests, accessibilité, documentation, recette, puis proposition de release.

Ne pas déclarer WEB-001 accepté sur la seule base d'un merge ou d'une CI verte.
