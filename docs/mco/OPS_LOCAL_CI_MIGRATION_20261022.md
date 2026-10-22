# OPS-LOCAL-CI — Préparation de migration OpenCode (22/10/2026)

Statut : **proposition non activée**. Aucune modification de main, aucun déploiement.

## Objectif
Exécuter les contrôles coûteux localement, en isolation, sans confondre exécution OpenCode et preuve indépendante. GitHub conserve PR, commits et statuts externes; Slack reçoit un CR métadonnées seulement.

## Contrôles obligatoires
1. Vérifier HEAD == SHA complet de la PR distante, checkout propre et commit immuable.
2. Exécuter le code candidat dans un conteneur/VM éphémère sans secrets, sans réseau vers les services privés, sans accès au socket Docker hôte, aux volumes métier ni au runner de livraison.
3. Reproduire la matrice Python 3.12/3.14, PostgreSQL 16 jetable, régression sans skip, benchmarks SQL, syntaxe JS, 18 parcours navigateur, pip-audit, Gitleaks, politique supply-chain, tests vidéo 75 s lorsqu'ils existent.
4. Produire une attestation JSON par SHA (version du plan, environnement, commandes, codes de retour, compteurs, durée, hashes des artefacts), signée par un service de confiance hors checkout. Un échec, skip, preuve manquante ou SHA changé interdit PASS.
5. Le service de publication, distinct du candidat, revalide la tête distante avant d'envoyer un statut GitHub. Ne jamais laisser le code testé accéder au token de publication ou à la clé de signature.
6. Slack : un message de fin OK/KO par exécution, lien PR, SHA, gates, erreurs catégorisées, prochaine action; aucun prompt, jeton, log brut ou donnée métier.
7. Revue humaine obligatoire avant fusion. Fusion et livraison PC sont des opérations séparées; SHA exact approuvé pour chaque livraison.

## Migration progressive
- Phase A : scripts et tests unitaires du contrôleur, exécution en mode shadow, comparaison aux anciens workflows.
- Phase B : publication de statuts externes et CR Slack après preuve sur PR témoin, avec déduplication et contrôle des erreurs réseau.
- Phase C : valider la politique de fusion et les droits GitHub (sur dépôt privé, la protection native peut nécessiter une offre adaptée).
- Phase D : seulement après validation explicite, réduire les déclenchements automatiques GitHub Actions; conserver le workflow de livraison PC verrouillé et un diagnostic manuel.

## État connu
- PR #214 en brouillon : ne pas fusionner.
- Les runners GitHub hébergés refusent le démarrage pour paiement ou plafond de dépenses; ce problème n'est pas résolu par la migration.
- LOCAL_PC_ENABLED et LOCAL_PC_APPROVED_SHA : ne pas modifier.
- Aucun statut vert ne peut être émis à partir d'un simple texte OpenCode.
- Les anciens workflows ne doivent pas être désactivés dans cette PR de préparation.

## Critères de recette
- Tests négatifs : SHA falsifié, suite ignorée, gate absente, signature invalide, PR mise à jour pendant les tests, tentative de fuite de secret, Slack indisponible.
- Vérification d'une PR témoin complète sur les deux versions Python, avec PostgreSQL isolé.
- Comparaison des résultats locaux et des résultats GitHub lorsque les runners sont de nouveau accessibles.
- Validation humaine du modèle de confiance avant bascule.
