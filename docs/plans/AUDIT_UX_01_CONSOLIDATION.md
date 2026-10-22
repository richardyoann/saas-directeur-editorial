# AUDIT-UX-01 — Consolidation ciblée du Studio

Date : 22 octobre 2026. Base vérifiée : `204d4c2c68a1853a6abd27587d05133cc0f41237`.
Branche corrective : `fix/AUDIT-UX-01-consolidation-studio`.
Le SHA livré est celui de la PR ; les preuves locales ci-dessous concernent son contenu source.

## Périmètre et limites

Les deux rapports OpenCode sur `0a34a243d5deb332aed7f307f560daf56388ce42`
n'ont pas été fournis ni retrouvés dans le dépôt ou les recherches GitHub.
Leur inventaire exhaustif reste à consolider après réception. Le tableau qualifie
uniquement les préoccupations explicites de la mission ; il ne reconstitue pas
les conclusions absentes et ne vaut pas audit de sécurité exhaustif.

## Qualification vérifiée

| Préoccupation | Qualification sur la base | Protection et changement | Preuve source/test dans cette PR |
|---|---|---|---|
| Approbation absente de `/studio/next` | Confirmé, corrigé | Relecture explicite et cases humaines avant chaque approbation ; endpoints existants conservés | `apps/web/arvor_next.js:346` (`humanReview`, `acceptNext`) ; `browser_checks/test_studio_browser.py:545` |
| Brouillon perdu ou inutilisable après 409 | Confirmé sur Studio classique ; partiellement confirmé sur next | Dialogue et champs conservés ; comparaison de la dernière révision ; adoption explicite de sa version ; aucun POST automatique | `apps/web/studio.js:719`, `apps/web/arvor_next.js:333` ; tests navigateur `:560`, `:579` |
| Actions incompatibles après approbation | Confirmé dans l'interface, contrôles serveur déjà présents | Approbation/rejet masqués sur étape acceptée ; révision autorisée ; storyboard périmé non approuvable | `apps/web/studio.js:350`, `apps/web/arvor_next.js:346` ; tests navigateur `:545` et scénario storyboard périmé existant |
| Absence de reprise après interruption | Partiellement confirmé : mécanisme serveur déjà présent | `reconcile_interrupted()` conservé ; projection GET en lecture seule et signal dans les deux interfaces ; action manuelle uniquement | `editorial/store.py:23`, `:38`, `:154`, `editorial/api.py:104` ; `tests/test_editorial_postgres.py:242`, `tests/test_studio.py:160`, navigateur `:654` |
| Course entre tentatives de connexion | Non démontré sur la pile actuelle | Middleware bornant et ingérant le corps avant la route ; aucun changement de production. 20 corps fragmentés concurrents : 5 refus 401 et 15 limitations 429 | `apps/api/request_limits.py`, `apps/api/studio.py` ; `tests/test_studio.py:192` |
| XSS Studio | Non démontré dans les familles et charges testées | Échappement existant, comparaisons ajoutées via textContent ; rendu réel Chromium, texte hostile visible sans nœud img/svg injecté ni exécution | Tests navigateur `:595`, `:625` : histoire, scènes, personnages, décors, couleurs, plans, émotions, sons, historique, médias, journal et onglets administratifs |
| CSRF / cross-tenant | Aucun contournement démontré | Origine et jeton avant mutation ; tenant issu de l'authentification ; protections conservées | `tests/test_studio.py:102`, `:115`, `:175` ; `tests/test_editorial_postgres.py:55`, `:86` et tests médias existants |
| Exposition `/ready` | Partiellement vérifié | GET réel local 200, ready=true ; écoute observée uniquement 127.0.0.1:8000, aucune écoute 443 observée | Observation read-only du service actif ; URL et trajet proxy/VPN réellement exposés non fournis, vérification externe impossible |
| Injection d'instructions dans brief | Garantie par prompt seule non démontrable | Donnée conservée dans enveloppe, sortie conforme au schéma exigée, tool_calls rejeté ; aucune affirmation d'immunité du modèle | `tests/test_audit_recovery.py:27` ; pas d'appel réel Qwen |

Les numéros de lignes identifient les entrées de fonctions/tests et non tous les contrôles internes.
Le seuil de dix minutes existant signifie **interruption suspectée**, pas preuve
que le worker est mort ou que le fournisseur n'a pas terminé. L'opérateur doit
vérifier l'état avant réconciliation. Celle-ci clôture l'incertitude en échec,
ne relance jamais Qwen et conserve les snapshots déjà confirmés.

## Validation réelle

- Régression Linux Ubuntu 26.04 / Python 3.14 : `scripts/run_regression.py`,
  **321 tests réussis, 0 échec, 0 erreur, 0 ignoré** sur PostgreSQL 16 jetable.
- Chromium réel : **23 tests réussis**. API/fournisseurs de la fixture simulés.
- Injection de pannes sur worker et véritable PostgreSQL : après begin_step,
  avant save_step, perte de connexion avant écriture et perte d'accusé après commit ;
  seconde prise sans rejeu ; nouvelle instance de magasin puis réconciliation
  manuelle idempotente. Historique confirmé préservé après accusé perdu.
- Tests existants conservés : approbation, concurrence, idempotence, audit/outbox,
  PNG, stockage et accès privés. Fournisseurs image/Qwen et échanges S3 simulés ;
  ces tests ne prouvent pas une intégration MinIO distante ou GPU réelle.
- Recette création → génération → relecture → approbation → image → stockage →
  récupération couverte par tests existants de navigateur/API/média ; elle n'est
  pas une recette continue sur les fournisseurs réels.

Aucun endpoint privé Qwen/image n'est configuré dans l'environnement candidat.
Aucune génération réelle, aucun rejeu IA ambigu, aucune mutation de données de
production, aucune migration, fusion ou activation PC n'a été exécuté.
Le `/ready` observé concerne le service installé, pas le candidat ni son SHA.

## Architecture et risques résiduels

Avant : le serveur possédait déjà les transactions et la réconciliation ; next
n'exposait pas les décisions humaines et les conflits pouvaient perdre le contexte.
Après : l'interface utilise les mêmes contrats de décision et une projection GET
additive `recovery`. Aucun changement du worker, du stockage, du schéma SQL,
des transactions métier ou des fournisseurs. Aucun timer n'effectue de POST.
La dernière révision n'est adoptée qu'après comparaison volontaire ; l'utilisateur
reste responsable de résoudre les différences avant une nouvelle soumission.

Les parcours XSS testés ne constituent pas une preuve universelle contre toute
charge. La limitation de connexion reste celle du processus existant, sans nouvelle
garantie distribuée. Les polls GET de next concernent uniquement queued/running.
La configuration et les prérequis d'installation restent inchangés.

Préalables à clôture complète : recevoir les rapports OpenCode, qualifier leur
inventaire, vérifier `/ready` via le trajet privé réel, effectuer la recette avec
Qwen/serveur image/MinIO réels et validation humaine autorisée. Vérifier aussi
les résultats CI sur le SHA exact. La PR reste brouillon jusque-là.

## MCO : traitement restant running

Symptôme : un traitement pris en charge reste running après une interruption.
Preuve : les quatre injections de panne ci-dessus reproduisent un état persistant
accessible depuis une nouvelle instance de magasin. Cause confirmée dans ces
injections : exception avant sauvegarde ou accusé PostgreSQL perdu ; cause d'un
incident réel : à déterminer par diagnostic, sans déduire un crash du seul délai.
Correction : visibilité de l'incertitude et accès manuel au mécanisme existant.
Validation : test PostgreSQL et test navigateur sans second appel fournisseur.
Limite : aucun kill réel du processus ni coupure réseau PostgreSQL physique ;
les pertes sont injectées aux frontières de méthodes.

Graphify AST a été reconstruit : 1 748 nœuds, 4 360 relations. Ce relevé ne
mesure pas une réduction de couplage : cette PR conserve les frontières média.
L'extracteur SQL optionnel est absent ; aucun paquet n'a été installé pour le
contourner. Les artefacts Graphify ne font pas partie du commit.
