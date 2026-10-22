# Arvor — migration CI locale OpenCode (candidat, non activé)

**État : PR brouillon ; aucune fusion, aucune livraison PC.** Ce changement prépare une CI locale reproductible et remplace, une fois sa PR validée/fusionnée, les déclenchements automatiques de huit workflows GitHub Actions par `workflow_dispatch` (usage manuel d'appoint). Le workflow `local-delivery.yml` et `chat-approved-delivery.yml` restent intégralement inchangés.

## Responsabilités et sécurité

- OpenCode : analyse et revue consultative, préparation des branches et PR. Aucun avis IA ne remplace un test ni la validation humaine.
- Contrôleur local **issu d'un checkout de confiance déjà relu** : vérifie SHA complet, ascendance Git et répertoire cible propre, puis exécute une liste fixe de commandes. Ne jamais exécuter le contrôleur depuis la PR non revue.
- Tests de la PR : conteneurs jetables avec répertoire source **en lecture seule**, privilèges limités, aucune variable métier, aucun montage du socket Docker ou des volumes PostgreSQL/MinIO de production. PostgreSQL 16 temporaire est lancé sans port publié et avec réseau isolé. Seul l'audit de dépendances utilise un conteneur distinct avec accès réseau sortant, mais sans aucun secret.
- Publication : dans une étape de confiance séparée. La clé HMAC et les jetons GitHub/Slack restent hors du dépôt et **hors de tous les conteneurs de test**. Rapport signé HMAC-SHA256 et lié au SHA ; logs privés en 0600. GitHub reçoit seulement un statut `arvor/local-ci` et la PR/Slack reçoivent le résumé et l'empreinte ; aucun prompt, réponse LLM, secret ni données métier.

## Neuf portes obligatoires

| Porte | Vérification |
| --- | --- |
| regression_312 / regression_314 | Suites unitaires complètes, PostgreSQL jetable, au moins 1 test, 0 erreur et 0 skip |
| sql_benchmark | Benchmark SQL sur données synthétiques |
| js_syntax | Syntaxe des 3 scripts JavaScript Studio |
| browser | Parcours Chromium réel avec API de test, au moins 1 test, 0 skip |
| dependency_audit | `pip-audit` sans tolérance à l'indisponibilité |
| secret_scan | `gitleaks` sur les commits entre base et tête |
| supply_chain | `scripts/ci_policy.py` |
| video_75 | Rendu FFmpeg synthétique 75 secondes et validation ffprobe |

Tout test manquant, ignoré, bloqué ou en échec interdit un résultat positif. Un statut « success » local ne prouve pas Qwen réel, GPU, recette artistique, validation humaine, sécurité absolue ou livraison sur PC. La PR #214 contient `scripts/smoke_video_75.py` ; tant qu'elle n'est pas fusionnée, une PR basée sur `main` ne disposant pas de ce script échouera correctement sur cette porte.

## Construction des images sur le PC (à faire après revue)

Depuis un checkout de confiance uniquement :

```bash
docker build -f ops/ci/Dockerfile --build-arg PYTHON_VERSION=3.12 -t arvor-ci:3.12 .
docker build -f ops/ci/Dockerfile --build-arg PYTHON_VERSION=3.14 -t arvor-ci:3.14 .
docker image inspect postgres:16 >/dev/null
command -v gitleaks
```

**Non réalisé dans cette préparation.** Examiner les sources, dépendances et digests des images avant exploitation, puis les figer explicitement dans une évolution revue. Le Dockerfile est une proposition, pas une installation ou une modification des conteneurs métier.

Créer une clé HMAC privée (répertoire 0700, fichier 0600) en dehors du dépôt : `openssl rand -out ~/.config/arvor-ci/attestation.key 48`. Fournir via coffre local `ARVOR_CI_HMAC_KEY_FILE`, `ARVOR_CI_GITHUB_TOKEN` (droits minimaux sur statuts/commentaires), `ARVOR_CI_SLACK_TOKEN` (écriture seulement), `ARVOR_CI_SLACK_CHANNEL` (canal privé). Ne pas laisser les jetons dans un fichier suivi par Git, dans les logs, dans l'historique shell ou dans les conteneurs.

## Exécution et compte rendu

Créer un worktree jetable sur le SHA exact de la PR, propre et indépendant du checkout `main`. Depuis le checkout de confiance :

```bash
export ARVOR_CI_HMAC_KEY_FILE="$HOME/.config/arvor-ci/attestation.key"
# Les autres jetons proviennent du coffre local ; ne jamais les mettre dans les commandes.
bash ops/ci/run_and_report.sh /chemin/worktree-pr SHA_COMPLET_40 BASE_SHA_COMPLET_40 NUMERO_PR
```

Le contrôleur écrit 9 résultats, y compris les échecs, et refuse un SHA incohérent, des images manquantes ou une base non isolée. Le signataire produit une preuve HMAC locale, puis le publisher re-vérifie que la PR est ouverte, ciblée sur `main` et que sa tête distante correspond exactement au SHA testé avant de publier le statut GitHub et le CR Slack. Les rapports comprennent les états des portes et une empreinte de l'attestation, jamais les logs bruts. En cas d'échec partiel de la publication Slack/GitHub, vérifier les actions déjà réalisées avant toute relance, pour éviter les doublons.

## Phase d'acceptation et limites

- Les **7 tests du format d'attestation** ont été exécutés avec succès hors du PC Arvor ; les images Docker, les neuf portes du dépôt, les permissions et l'envoi Slack par ce nouveau dispositif n'ont **pas** été testés sur ton PC.
- La protection de branche GitHub n'est pas disponible actuellement dans ce dépôt privé avec son offre actuelle. Un statut externe seul **n'empêche pas techniquement une fusion** : la revue humaine et la vérification explicite du statut/SHA restent obligatoires. Ne pas ajouter d'auto-merge.
- Les exigences anciennes de CI GitHub verte des PR #208/#209 ne sont pas rétroactivement levées : leur modification nécessite une décision de gouvernance et des preuves sur le SHA exact. Ne pas fusionner la PR #214 à ce stade.
- Conserver `LOCAL_PC_ENABLED`, `LOCAL_PC_APPROVED_SHA`, `local-delivery.yml` et `chat-approved-delivery.yml` inchangés. L'installation ou la MEP PC exige une autorisation distincte mentionnant le SHA **complet**. Pas de migration métier, pas de rollback ni de modification de services.
- Avant activation : exécuter les neuf contrôles sur une PR témoin dans des conteneurs isolés, vérifier les signatures, l'absence de secrets, les retours Slack et les permissions GitHub ; revue indépendante puis décision explicite de fusion de la PR de migration.
