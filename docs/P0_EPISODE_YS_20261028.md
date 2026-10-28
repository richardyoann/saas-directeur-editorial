# P0 — Épisode Ys et prototype cohérent, preuves du 28 octobre 2026

Statut : **preuve technique locale réalisée**, aucune fusion, aucun déploiement
PC, aucune publication. Les validations humaine/audiovisuelle indépendante et
de capitalisation restent **en attente** ; ce rapport ne les remplace pas.

## 1. Périmètre et environnement

| Élément | Valeur |
| --- | --- |
| Dépôt de travail | `/tmp/opencode/mvp-video`, branche `feat/p0-ys-20261028`, base `24e49d3bd4ee846c51822ba0cc0e3c48bdf542fc` |
| API isolée | `127.0.0.1:8021`, un worker Uvicorn |
| PostgreSQL | base jetable `episode_ys_20261028` dans `po-mvp-test`, `127.0.0.1:55491` |
| Stockage | backend fichiers privé `/tmp/opencode/episode-ys/media`, aucun bucket métier |
| Qwen | llama.cpp `172.31.48.1:8081`, `qwen2.5-3b-instruct-q4_k_m.gguf` |
| Images | sd.cpp `172.31.48.1:8082`, SD 1.5, 512×512, 20 steps, CFG 7, `euler_a` |
| Voix | Piper local `fr_FR-siwis-medium.onnx` |
| Montage | FFmpeg 8.0.1, profil `cinematic` |
| MLflow | `http://127.0.0.1:5000`, version 3.17.2, TLS vérifié par la CA MinIO existante |

Aucune base métier, aucun bucket, aucun volume Docker métier, aucun secret et
aucun service payant n'ont été modifiés ou utilisés. Le runtime déployé
`127.0.0.1:8000` n'a pas été touché.

## 2. P0-A — MLflow fiable et non bloquant

- `~/.config/arvor-mlflow/client.env` (0600, hors dépôt) contient
  `REQUESTS_CA_BUNDLE` et `AWS_CA_BUNDLE` vers la CA MinIO existante.
- `infrastructure/observability/mlflow_env.py` charge explicitement ce fichier
  via `ARVOR_MLFLOW_ENV_FILE`, avec liste d'autorisation, refus des liens
  symboliques, permissions et CA invalides ; le démarrage reste fail-open.
- `scripts/mlflow_healthcheck.py --env-file … --full` :
  `healthy=true`, `artifact_roundtrip=true`, 8 expériences, 3,58 s.
- Panne réelle puis reprise : URI morte, premier rejeu `replayed=1`, second
  `replayed=0`, exactement un run créé. Le spool ne contient ni prompt ni
  réponse.
- Les runs des deux histoires et les 8 lignes média de l'épisode sont toujours
  présents après redémarrage de l'API isolée ; aucun doublon de run n'a été
  observé au rejeu.

Interdits respectés : aucun `verify=False`, aucun `MLFLOW_S3_IGNORE_TLS=true`,
aucun port MLflow/MinIO publié, aucun identifiant ou certificat dans le dépôt.

## 3. P0-B — Télémétrie des quatre expériences

Deux histoires distinctes, jamais mélangées :

| Histoire | Rôle | Scènes | Durée | Runs |
| --- | --- | --- | --- | --- |
| `be520301-a010-595e-8b6c-840c340924aa` | épisode final | 5 | 75 s | 2 scénario, 5 images, 1 voix, 2 exports |
| `875b28c0-38f4-5619-af78-8f7a840832ad` | prototype cohérence | 3 | 45 s | 2 scénario, 3 images, 1 voix, 2 exports |

Paramètres enregistrés :

| Expérience | Paramètres / mesures |
| --- | --- |
| scénario | modèle Qwen 3B, prompt `1.2.0`, `temperature=0.1`, `max_tokens=2048`, durée analyse 13,354 s et storyboard 60,518 s pour l'épisode |
| images | modèle `sd-cpp-local`, prompt `2.0.0`, 512×512, seed déterministe par scène, `euler_a`, 20 steps, CFG 7, scheduler `discrete`, SHA-256 PNG, durée 160–164 s |
| voix | Piper, voix `fr_FR-siwis-medium.onnx`, SHA-256 WAV, octets, 75,000 s, cible 75 s |
| vidéo | 1080×1920, 24 fps, H.264/AAC, Ken Burns, fondus, sous-titres incrustés + SRT, SHA-256, octets, durée d'encodage |

Exemples d'empreintes image (épisode) :

| Scène | PNG SHA-256 | Octets | Durée |
| --- | --- | --- | --- |
| 1 | `21e44c0167fbb27d52eff91a9d8bbef7ff20e99badb6aaf5c052636887920bbf` | 524 989 | 160,786 s |
| 2 | `174a797ec7b6b0f644dae4e08243629f3a309ef0b89b59dfad6ed50b0b801f29` | 654 057 | 161,226 s |
| 3 | `b180a80215faa4fa8ef7b4256c2011c8e2cbd32c9fb14bca672f9872f7318be8` | 567 411 | 161,086 s |
| 4 | `f6c39b9bc9f2a01241a4c4563c8a582b61c6e51d40e5afea8b5f68db0b77b502` | 749 243 | 161,896 s |
| 5 | `abc52522a05eb44827c53a27aea024c1fe95b26a4cad168114af66b97ac4cfac` | 641 031 | 163,793 s |

Les runs rejetés sont conservés et étiquetés, pas supprimés :

- `3e98a00c24bd42bdb8f71e8c8412d88f` : export épisode superseded, motif
  `caption_layout_rejected` ;
- `e6849ca135aa4a7ab8f0fccf3dda7953` : export épisode accepté techniquement,
  SHA `be84da20da4fcb038a61cd6f65ebbfbb251d73a98d3101d520eddd2b7142ce5d` ;
- `b718dca0626e4d68aed803ffe616aa9c` : export prototype superseded ;
- `0aaf50f8a0424a02bbb3df6bf4693f78` : export prototype accepté techniquement,
  SHA `23d7a2aa934e0a9aeb4ff7f37e85e56eaffc74600b610f75b75d130f818b4e42`.

Chaque run accepté porte `arvor_validation_status=technical_accepted`,
`arvor_validator=open-code-operator`,
`arvor_independent_validation=pending`. Aucune validation humaine n'est
revendiquée.

Limite : les images de l'épisode ont été générées avant l'étiquette
`sd-cpp-local` et la version de prompt image ; leurs runs portent
`sd.cpp-compatible` et n'ont pas `prompt_version`. Les images du prototype,
générées après, portent les deux.

## 4. P0-C — Épisode 5 scènes et prototype 3 scènes

### 4.1 Épisode accepté

| Média | Mesure |
| --- | --- |
| voix | `db325722330a28d951f0774189f937dc7b9b178c5b0df863dd5a74dbb7a43dd2`, 3 600 044 octets, 75,000 s |
| vidéo | `be84da20da4fcb038a61cd6f65ebbfbb251d73a98d3101d520eddd2b7142ce5d`, 18 248 959 octets, 75,000 s, 1080×1920, 24 fps, H.264 + AAC, tentative 5 |
| SRT | `a489296c2658f008b0f93b5cc75b184fd41b857018746b339d40585d3b1ef0f1`, 697 octets, 5 repères de 15 s |
| sous-titres incrustés | pixels quasi blancs mesurés dans le tiers inférieur aux instants 5 s et 65 s |

Les exports 3 et 4 ont été rejetés : légendes surdimensionnées au milieu de
l'image avec l'ancien filtre SRT, puis correction non chargée par le processus
API. Le rendu utilise désormais un ASS privé avec `PlayResX/PlayResY`
explicites. Le processus API a été redémarré, l'export 5 est le seul accepté.

### 4.2 Prototype cohérent 45 s

| Élément | Mesure |
| --- | --- |
| images | 3 PNG 512×512, SHA `b83ebc41…`, `ecc8f7fe…`, `ea817d9c…` |
| voix | `16147e74752a4f4a0ccd26d307f6228ab70496c8eba3839c97a0f20c9329bad5`, 2 160 044 octets, 45,000 s |
| vidéo | `23d7a2aa934e0a9aeb4ff7f37e85e56eaffc74600b610f75b75d130f818b4e42`, 10 792 654 octets, 45,000 s, 1080×1920, H.264 + AAC |
| SRT | `a4757687f62c91c02c9a034518f6b9895c48ec4d9a8a16fac4559fd28cf880d0`, 447 octets |

Cohérence mesurée :

- les trois prompts finaux contiennent le **même descripteur de Gradlon**
  (« roi âgé à barbe grise, couronne d'or, manteau pourpre brodé, regard
  grave ») et la même distribution de rôles ;
- distances dHash par paires : 25, 26 et 27 (compositions distinctes, pas trois
  copies) ;
- piper et FFmpeg ont réellement produit les médias.

Limite : aucune reconnaissance faciale ni score sémantique d'identité n'est
disponible. La cohérence est prouvée au niveau du prompt et par mesure
perceptuelle globale, pas par une identité visuelle certifiée. Une revue
humaine reste nécessaire.

### 4.3 Sources et statut éditorial

Ys, Gradlon, Dahut, Guénolé et Morvarc'h relèvent de la **tradition légendaire
bretonne**. Les formulations, enchaînements, descriptions visuelles, images,
voix et montage de cet épisode sont des ajouts générés pour cette exécution.
**Aucune source documentaire n'a été collectée ni versée dans ce dossier de
preuve.** L'épisode doit donc être présenté comme une fiction inspirée de la
légende, jamais comme un documentaire historique ou un média réel. Aucune
publication n'a été faite.

## 5. P0-D — Chaîne de livraison et exposition

- Le workflow `chat-approved-delivery.yml` reste déclenché par la création
  d'une branche `delivery-approved/*`, mais le job auto-hébergé exige en plus
  `vars.LOCAL_PC_ENABLED == 'true'` et
  `vars.LOCAL_PC_APPROVED_SHA == needs.validate.outputs.sha`. La création de
  branche seule ne peut donc plus installer quoi que ce soit.
- Le job vérifie le SHA complet (40 hexadécimaux), l'égalité avec le SHA validé
  et `git rev-parse HEAD`. `scripts/deploy_local.py` refait le contrôle.
- Permissions du workflow : `contents: read`, `actions: read`. Le PostgreSQL du
  job est un service à port éphémère `5432/tcp`, sans publication sur l'hôte.
- Les conteneurs locaux vérifiés sont liés à la boucle locale :
  `po-mvp-test 127.0.0.1:55491`, `editorial-postgres 127.0.0.1:5432`,
  `editorial-minio 127.0.0.1:9000-9001`.
- `.github/CODEOWNERS` documente les surfaces sensibles. La protection de
  branche et l'application forcée des CODEOWNERS ne sont **pas disponibles**
  sur le plan GitHub actuel du dépôt privé ; le contrôle réellement appliqué
  reste la variable de livraison et la revue de PR.
- Aucun job auto-hébergé n'a été déclenché, aucun déploiement PC n'a eu lieu.

## 6. Tests exécutés

- Suite locale complète : **595 tests exécutés, 0 échec, 54 ignorés** faute de
  prérequis d'environnement. Ces 54 ignorés ne sont **pas** comptés comme
  réussite et ne constituent pas une qualification CI.
- Sélection P0 sans aucun saut : **119 tests OK**, dont MLflow, client privé,
  tracker, instrumentation, sd.cpp, règles média, production média, stockage,
  export réel FFmpeg, sous-titres incrustés, Piper, politique CI et livraison
  isolée.
- `tests/test_render_episode.py` vérifie désormais, sur une vidéo réelle, que
  des pixels clairs existent dans le tiers inférieur d'une scène bleue unie :
  une légende déclarée mais invisible ferait échouer le test.
- La correction du backend fichiers est couverte : une image enregistrée sans
  référence ne pouvait pas être montée (`media_incomplete`). Les 8 références
  déjà générées dans la base jetable ont été complétées après vérification du
  SHA-256, sans régénération ni modification de média métier.

## 7. Recette finale — état exact

| Critère | État |
| --- | --- |
| `story_id` unique et médias rattachés au même épisode | oui pour l'épisode |
| Qwen, 5 images, 1 voix, 1 vidéo sous le même identifiant | oui |
| paramètres, mesures, statuts, SHA-256 | oui, sauf `prompt_version` image de l'épisode (antérieur au correctif) |
| persistance après redémarrage | oui |
| rejeu du spool sans doublon | oui |
| validation audiovisuelle indépendante | **non, en attente** |
| validation de capitalisation | **non, en attente** |
| publication de l'épisode | aucune |
| déploiement PC | aucun, SHA non approuvé |
| service payant ou modèle externe | aucun |

Décision : l'épisode et le prototype sont **prêts pour revue humaine**, pas
pour publication ni livraison. La fusion des PR et toute livraison PC exigent
une nouvelle validation explicite, et pour le PC l'approbation du SHA complet
exact.
