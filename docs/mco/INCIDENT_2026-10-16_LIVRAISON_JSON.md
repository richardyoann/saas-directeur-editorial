# Incident du 16 octobre 2026 — livraison bloquée avant activation

## Symptôme et preuves

SHA autorisé : `26dbefea2e7bd5eef870c1ea787644b521f12aca`.
[Livraison #38933022033](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38933022033)
sur `editorial-pc-ubuntu2604`. Aucun contenu métier ou secret n'est reproduit.

- Tentative 1 : garde shell refusée, `LOCAL_PC_ENABLED=True`, alors que le
  contrat exige exactement `true`. Installation et tests ignorés.
- L'utilisateur a indiqué avoir corrigé cette valeur. Tentative 2 : garde
  réussie, dépendances et base jetable préparées, puis 252 tests exécutés :
  250 réussis, 2 échecs, aucune erreur ni skip. Activation bloquée.
- Échecs : `test_deep_api_json_returns_422_before_authentication` et
  `test_deep_studio_json_returns_422` : HTTP 401 au lieu de 422.
- Les traces du runner désignent `/usr/lib/python3.14/asyncio/`. La CI
  réussie de ce SHA utilisait Python 3.12 ; elle ne couvrait pas cet interpréteur.

## Cause et correction

La casse du flag est une cause confirmée par les logs et le succès de la
garde à la tentative suivante. Ne pas confondre ce défaut avec un runner absent.

Le contrôle de profondeur JSON s'appuyait uniquement sur `RecursionError`
émise par `json.loads`. C'est un comportement d'implémentation, pas une limite
applicative portable. Le runner Python 3.14 a atteint l'authentification pour
ces JSON imbriqués au lieu du refus 422 attendu.

Correction : parcours itératif du résultat JSON, limite de 128 niveaux de
conteneurs, même fonction pour le middleware API et le parseur Studio.
Conserver aussi le traitement de RecursionError pour les décodeurs récursifs.
Les tests vérifient la borne exacte, les objets, les chaînes contenant des
crochets et le résultat d'un décodeur non récursif simulé. La CI complète
utilise désormais les matrices Python 3.12 et 3.14 avec PostgreSQL jetable.

Reproduction locale sur Python 3.14.8 : le décodeur standard accepte les
15 000 tableaux imbriqués ; le nouveau contrôle refuse ce même JSON.
128 niveaux sont acceptés, 129 refusés. Python 3.12 : 16 tests ciblés réussis ;
suite locale 255 tests, 214 réussis et 41 PostgreSQL ignorés faute de base
dédiée, aucun échec/erreur. Les résultats complets des deux versions sont
consignés séparément en CI sur le SHA du correctif ; aucun skip local n'est
présenté comme une validation de livraison.

## Reprise sans effet métier ambigu

Ne relancer que les jobs échoués lorsqu'il est prouvé que l'installation n'a
pas atteint les sondes métier. Ici les échecs précèdent le démarrage du candidat
et la bascule de `current` dans `deploy_local.py` ; aucun appel Qwen réel
n'a été atteint par ces tentatives. Ne pas supprimer les releases candidates,
les volumes, la branche d'approbation ou les données pour contourner le gate.

Le nouveau correctif nécessite une nouvelle CI au SHA exact, puis validation
explicite de son SHA final avant toute livraison PC. Le succès de la CI ne
prouve pas une activation, une restauration ni une recette éditoriale.
La version active n'a pas été inspectée directement pendant ce diagnostic.

## Retour arrière et limites

Aucune migration, dépendance runtime ou modification des secrets.
Revenir à la release active précédente si nécessaire, après contrôle de son
reçu et du service. La nouvelle limite peut refuser un client envoyant plus
de 128 niveaux ; les contrats éditoriaux ordinaires sont beaucoup moins profonds.
Ce rapport ne clôt pas la recette PC : consigner le run réussi et le reçu après
livraison autorisée. Conserver `LOCAL_PC_ENABLED` en minuscules ; la garde SHA
exact et les contrôles de livraison restent obligatoires.
