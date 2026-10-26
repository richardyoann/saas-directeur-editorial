# Décision et procédure — finalisation #214/#215

Autorisation utilisateur du 26 octobre 2026 : corrections, tests, revue automatisée
indépendante et fusions normales de #214 puis #215, sans livraison PC, dépenses,
modification des secrets existants, données ou protections. Cette décision remplace
pour ces PR les anciennes mentions imposant une nouvelle validation intermédiaire.
Une analyse IA reste identifiée comme telle, jamais comme une approbation humaine.

## Politique de qualité et limite GitHub

GET branches/main indique protected=false, required_status_checks vide. Les API
protection/rulesets répondent 403 (offre privée actuelle). Aucun contrôle n'a été
retiré. Le statut local est informatif dans GitHub : il ne bloque pas un utilisateur
qui fusionnerait directement dans l'UI. La procédure obligatoire de cette mission
est scripts/arvor_ci_merge.py : manifeste signé par autorité hôte extérieure,
clé publique épinglée par SHA256, revue finale correspondant aux SHA tête/base,
preuves de moins de deux heures et contrôles obligatoires réussis, puis relecture
des HEAD distants et merge normal sans --admin. GitHub conserve ses propres refus.
Toute évolution de tête/base invalide les preuves. Aucun statut d'infrastructure
hébergée en échec avant démarrage n'est une preuve d'échec applicatif.

Les huit workflows hébergés de tests/triage passent explicitement en déclenchement
manuel (workflow_dispatch), sans changer pins, permissions ni tests locaux. Ce
changement de gouvernance est revu dans #215 ; il élimine les déclenchements PR,
push/schedule et cascades workflow_run payants après fusion. Les deux voies de
livraison restent intactes, verrouillées sur LOCAL_PC_APPROVED_SHA exact. Aucun
workflow manuel ne sera lancé pendant cette mission. Le merge #214 utilise un
message [skip ci], avant que la politique locale #215 soit présente dans main.

## Chaîne extérieure et bootstrap

1. Revue indépendante du diff contrôleur et de ses tests ; pas d'auto-approbation.
2. Tests contrôleur Python 3.12/3.14, image construite avec audit PyPI frais,
   isolation vérifiée sur l'inspection Docker réelle.
3. Candidat métier #214 testé par le contrôleur propre/pinné dans un clone séparé :
   16 gates, zéro skip, journaux hôte privés non montés, code retour Docker observé.
4. Vérification séparée reçu/observation/16 logs, signature Ed25519 depuis l'hôte,
   vérification par clé publique et publisher relisant HEAD/base distants. Le champ
   de provenance n'est jamais positionné manuellement. Slack si configuré seulement.
5. Bootstrap du contrôleur #215 : exécution séparée supervisée depuis un programme
   hôte extérieur au checkout et revu, conteneur sans réseau/secrets, politiques
   épinglées RO. Pas d'exception dans enforce_policy_not_self_modified, pas de reçu
   prétendant que le contrôleur s'est certifié comme candidat métier. La
   qualification de bootstrap est signée/vérifiée par OpenSSL système, hors du
   code candidat et de son mécanisme d'attestation à valider.
6. Manifeste de fusion externe signé, résultats et revue exacts, dry-run du gate,
   fusion normale #214 ; vérification GitHub merged et main.
7. Merge propre du nouveau main dans #215 ; nouvelle image/qualification/revue
   pour cette tête/base, ready puis fusion normale via le même gate procédural.

## Correctifs démontrés avant gel

- Imports os/stat manquants : NameError du CLI de signature reproduit ; nouveau
  test positif et refus d'une clé 0644 avant signature.
- Collecteur unittest : erreurs de cleanup/fixtures absentes du bilan observé.
  Compteurs conservateurs réunissant erreurs runtime et résultat framework ;
  tests négatifs cleanup, setUpModule et tearDownClass.

Les résultats définitifs doivent être publiés après gel dans les commentaires
GitHub et les preuves privées, afin de conserver les identités certifiées.
Aucun test ignoré, aucune réussite simulée ni ancien reçu ne valide une fusion.

## Intégration concurrente préservée

Les commits distants bb2c45d/6e92183 ont été fusionnés sans réécriture. Les pins
hôte fixes ~/.config/arvor-local-ci/trust.json restent obligatoires pour signer
et publier : contrôleur/image/politique/clé et chemin signataire vérifiés. Une
variable de provenance/réussite ne remplace aucune de ces vérifications. Les
dispatchs asyncio standards sont distingués des overrides candidats interdits.
Les tests de ces pins et du gate de fusion sont inclus au lanceur de qualification.
