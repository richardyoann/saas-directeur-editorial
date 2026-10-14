# WEB-001 — Contrat de parcours navigateur privé

Issue : #71. Ce document est une spécification d'implémentation, **pas une preuve de fonctionnalité livrée**.

## Contrats API vérifiés au SHA de conception

Routes existantes :

- `POST /editorial/runs` avec `Idempotency-Key` UUID ;
- `GET /editorial/runs/{run_id}` ;
- `GET /editorial/runs/{run_id}/history` ;
- `POST /editorial/runs/{run_id}/steps/{analysis|storyboard}/review` ;
- `GET /editorial/runs/{run_id}/reviews?limit=…&before_revision=…`.

Il n'existe actuellement ni route de liste des histoires/exécutions, ni connexion utilisateur, ni gestion de session web. Le développement doit ajouter un contrat de lecture paginé, isolé par tenant, ou limiter explicitement le MVP à l'ouverture d'un `run_id` connu. Aucun écran ne doit supposer un endpoint absent.

## Parcours MVP

1. Ouvrir l'application privée et établir une session web côté serveur.
2. Consulter les exécutions du tenant via la future route de liste validée, ou ouvrir une exécution connue.
3. Voir scénario, scènes, analyse, storyboard et états de validation.
4. Consulter les deux étapes avec leurs réponses structurées et versions.
5. Accepter, rejeter ou demander une révision via les routes existantes, avec confirmation explicite.
6. Rafraîchir l'état, puis consulter l'historique des traitements et les décisions paginées.

## Authentification et sécurité

- Le navigateur ne reçoit jamais `EDITORIAL_API_TOKEN`, `EDITORIAL_TENANT_ID` ou `EDITORIAL_ACTOR_ID`.
- Un composant web côté serveur conserve les secrets, crée une session protégée (`HttpOnly`, `Secure`, `SameSite`) et appelle l'API.
- Les mutations exigent une protection CSRF et n'acceptent jamais tenant/acteur depuis le navigateur.
- La fermeture ou l'expiration de session invalide l'accès côté serveur.
- L'isolation multi-tenant doit être vérifiée sur chaque lecture et mutation.

## États d'interface et cas d'échec

- Chargement, absence de données, réponse invalide, expiration de session et service indisponible.
- 401 : session absente ou expirée ; revenir à l'écran d'accès sans boucle automatique.
- 404 : objet absent ou appartenant à un autre tenant, sans révéler son existence.
- 409 : décision périmée/conflit ; recharger sans réémettre automatiquement la mutation.
- 422 : entrée ou révision incompatible ; afficher une erreur compréhensible sans journaliser prompt ni sortie.
- 502/503/504 : conserver l'action utilisateur, proposer une reprise explicite et ne pas prétendre que la mutation a réussi.
- Aucun 403 n'est attendu du contrat API actuel ; l'ajouter seulement avec une future règle d'autorisation testée.
- Une révision de l'analyse rend le storyboard précédent obsolète et doit être signalée.
- Aucun résultat IA n'est approuvé automatiquement.

## Tests et critères de livraison

- Tests d'affichage, navigation clavier, mobile et PC.
- Tests de session, CSRF, absence de secrets dans les ressources navigateur et journaux.
- Tests d'isolation multi-tenant, pagination, décisions concurrentes, idempotence et absence de rejeu automatique après 409/erreur ambiguë.
- Tests PostgreSQL isolés, contrats HTTP réels et intégration avec Qwen réel avant qualification finale.
- Preuve datée : SHA, commande, résultats, type de test, préconditions et critères couverts.
- Revue du diff complet, CI sans skip, documentation MCO, sauvegarde et retour arrière.
- Après fusion validée et contrôles réussis sur le SHA courant, l'installation privée autorisée peut être exécutée sans nouvelle confirmation ; elle ne constitue pas une acceptation éditoriale humaine.

## Ordre de réalisation

A. Ajouter et tester le contrat paginé de liste, ou borner le MVP à un `run_id` connu.
B. Mettre en place la session web côté serveur et les protections CSRF.
C. Développer liste/détail en lecture seule.
D. Ajouter décisions de revue et historiques.
E. Exécuter tests, accessibilité, documentation, recette, livraison privée et retour arrière.

Ne pas déclarer WEB-001 accepté sur la seule base d'un merge, d'une CI verte ou d'une installation technique.
