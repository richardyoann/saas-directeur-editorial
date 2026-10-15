# REL-002 — Livraison privée sans écriture métier pendant la recette

## Constat et objectif

Le SHA antérieur `4dd6aaab92d15f8d2c5a2671cf7ed55c86dcde31` fait
fonctionner les tests mais la livraison appelait `POST /editorial/runs`
sur la base métier privée. **Ne pas activer le workflow de cette ancienne
version** lorsqu'on exige que les données utilisateur restent intactes.

Le correctif REL-002 sépare :
- **Candidate en environnement jetable** : API de la nouvelle release lancée
  sur port local éphémère, `PO_DATABASE_URL` remplacée exclusivement dans
  le sous-processus par la base PostgreSQL du service CI `po_test`, tenant
  et acteur éphémères, mode asynchrone désactivé. La migration de schéma
  éditorial ne s'exécute que sur la DB jetable. Le test Qwen complet
  analyse/storyboard/idempotence y écrit ses résultats ; ces écritures sont
  **attendues uniquement sur la DB de test**.
- **Service actif / base métier privée** : contrôles GET /health, GET /ready,
  GET /editorial/runs?limit=1 avec jeton Bearer et test 401 anonyme.
  La vérification Studio charge les assets, ouvre et ferme une session
  **volatile en mémoire**, effectue un GET de liste, sans nouvelle histoire,
  suppression ni migration. Le test graphique réel n'est pas automatiquement
  exécuté pendant la livraison.
- **Rollback** : en cas d'échec des contrôles après bascule, le lien
  `current` et le service retournent à la release antérieure. Les répertoires
  de releases précédents sont conservés ; `last_delivery.json` n'est écrit
  qu'après succès de la recette.

La procédure **prépare une release isolée et installe les dépendances Python
nécessaires dans son propre venv** : ne pas confondre « aucune mutation
métier » avec « aucune écriture sur le disque du PC ». Elle redémarre aussi
`editorial-api.service`. Aucun composant graphique, modèle, pilote GPU ou
moteur d'images n'est téléchargé ou installé par ce workflow.

## Double verrou d'autorisation sur GitHub

- `LOCAL_PC_ENABLED=false` par défaut : tout job de livraison est ignoré.
- `LOCAL_PC_APPROVED_SHA` doit contenir le **SHA complet exact de main**
  expressément validé pour la livraison. L'ancien accord sur un ancien SHA
  ne s'applique jamais à un SHA modifié.
- `.github/workflows/local-delivery.yml` refuse tout job si l'un de ces
  verrous manque, si le run ne vient pas de `main`, ou si la CI liée a échoué.
- Le job vérifie aussi que le checkout correspond au SHA approuvé.
- `deploy_local.py` vérifie *de nouveau* l'approbation, la HEAD de
  `main` et les succès des deux workflows GitHub
  `Full regression` et `Dependency security audit` pour **ce SHA**.

Deux déclenchements sont possibles :
1. Automatique après la CI d'un push `main`, seulement si l'accord SHA et
   les verrous sont déjà actifs ; ne pas garder le flag activé durablement.
2. Manuel dans GitHub Actions → **Private PC delivery** → Run workflow,
   branche `main`, champ `approved_sha` exactement égal au SHA autorisé.
   Le job vérifie quand même les deux preuves CI du commit.

**Important** : ne pas supposer qu'un workflow `skipped` peut être réutilisé
simplement après modification de variables. Préférer le déclenchement manuel
documenté et recontrôler que le SHA n'a pas changé.

## Avant déploiement — vérifications sur le PC, sans mutation

Examiner la version active `last_delivery.json`, le lien `current`,
l'identité du runner WSL Ubuntu 26.04, la présence des chemins privés
`LOCAL_RELEASE_ROOT` et `LOCAL_CONFIG_PATH` et les permissions.
Vérifier un point de restauration et un export/snapshot de la base
**sans lancer de migration**. Une liste `pg_restore -l` ne prouve pas
qu'une restauration complète est possible : tester séparément sur DB isolée.

Lire le résultat de
`scripts/diagnose_vulkan_windows.ps1` et
`scripts/diagnose_image_runtime.py` : ces diagnostics sont facultatifs
pour la livraison du socle éditorial et **ne prouvent pas** que l'image réelle
est prête. Ne pas modifier le pilote AMD ou installer sd.cpp sur simple
succès de la CI.

La base métier utilisée dans `LOCAL_CONFIG_PATH` doit être **distincte**
du conteneur `po_test`. Les contrôles refusent l'URL de test si identité
DB/nom/port/rôle non conformes. **Ne pas copier les secrets GitHub ou la
configuration privée dans un ticket ou des logs.**

## Tests préalables obligatoires

```bash
python scripts/run_regression.py
python -m unittest tests.test_isolated_delivery -v
```

Le workflow GitHub exécute la régression Python/PostgreSQL sur CI jetable.
Les tests du lot prouvent le contrôle du tenant isolé, le rejet des URLs
métier ambiguës, les requêtes GET uniquement sur le runtime actif,
l'absence de génération éditoriale active et le verrou SHA / preuves CI.
Le test local et la CI ne remplacent pas la preuve du runner PC.

## Recette à constater dans le run PC

- Contrôle `main` + SHA approuvé ; CI et audit exacts ; variables présentes.
- Service et chemin du runner vérifiés ; ancienne release préservée.
- Nouvelle release préparée avec venv propre, tests complets réussis.
- Génération de Qwen et traitement éditorial en **base jetable** (pas privé).
- Bascule du lien `current` puis restart du service utilisateur.
- GET /health, GET /ready, GET /editorial/runs, session Studio, rendu HTML/JS.
- `last_delivery.json` consigne SHA et résultats.
- Après livraison, mettre immédiatement `LOCAL_PC_ENABLED=false`.
- Vérifier absence de nouveaux runs de recette dans la base métier,
  et comparer les états avant/après **sans stocker de secrets**.

Si la validation après activation échoue : retrouver le journal de job,
l'ancienne release et la preuve de rollback. Ne pas enchaîner des retries
automatiques d'une génération LLM ambiguë.

## Ce qui reste séparé de ce lot

- Test d'images réelles avec `stable-diffusion.cpp` et Vulkan sur Radeon
  RX 580 : nécessite vérification matériel et une autorisation d'installation
  distincte.
- Recette manuelle de qualité éditoriale et des personnages.
- Sauvegarde/restauration réelle de la base dans environnement isolé, si
  non déjà prouvée avec la version visée.

Ce guide documente le **code de livraison proposé**. Tant que le SHA correctif
n'est pas fusionné, approuvé puis exécuté sur le runner PC, il ne faut pas
annoncer une MEP terminée.
