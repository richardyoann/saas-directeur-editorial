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

## Modèle de confiance à implémenter
- La liste des gates et leurs versions provient d'une politique approuvée et épinglée hors du checkout candidat. Une PR ne peut ni retirer une gate, ni assouplir un seuil, ni substituer une commande tout en conservant un statut vert.
- La préparation des dépendances utilise des versions verrouillées dans une phase séparée; l'exécution du candidat est ensuite hors ligne, sans secrets, sans socket Docker hôte et sans montage des données métier.
- L'attestation contient au minimum dépôt, numéro de PR, SHA de tête et de base complets, identifiant d'exécution non réutilisable, horodatages début/fin, version de politique, gates attendues/exécutées, commandes normalisées, codes de retour, compteurs de tests et hashes des artefacts.
- Le JSON est sérialisé canoniquement avant signature. La signature asymétrique, son algorithme, l'identifiant de clé et la clé publique épinglée sont vérifiés par le service de publication; la clé privée reste hors du checkout, du conteneur testé et des logs.
- Le service de publication refuse une attestation expirée, rejouée, liée à un autre dépôt/PR/SHA, incomplète ou signée par une clé inconnue. Il relit le HEAD distant juste avant publication et publie `failure` ou aucun statut si le SHA a changé.
- Les contextes de statut sont fixes et documentés. Tant que `main` n'est pas protégé par un ruleset ou une règle équivalente, ces statuts restent informatifs et ne constituent pas une barrière technique de fusion.
- Les journaux détaillés restent dans un stockage privé à rétention bornée avec filtrage des secrets; Slack ne reçoit que les métadonnées prévues et un identifiant de preuve.

## Critères d'échec supplémentaires
- Politique de gates absente, modifiée par le candidat ou version non approuvée.
- Attestation périmée, rejouée, non canonique, d'un autre dépôt/PR/base/HEAD, ou clé révoquée/inconnue.
- Dépendance non verrouillée, accès réseau imprévu pendant l'exécution, montage d'un volume métier ou accès au socket Docker hôte.
- Publication impossible ou HEAD distant modifié entre la recette et l'envoi du statut.
- Absence de protection de branche : aucune automatisation ne doit alors interpréter le statut local comme autorisation de fusion.

