# MLflow privé Arvor — intégration, exploitation et preuves

Statut au 28 octobre 2026 : **qualifié localement sur WSL et en CI locale
16/16**, branche poussée et PR #225 ouverte, **non fusionné** et **non déployé
sur le PC**. Le serveur MLflow est un service utilisateur systemd privé, sur
loopback, avec PostgreSQL et MinIO dédiés. PostgreSQL Arvor reste la source de
vérité métier ; MLflow ne contient que des expériences, mesures, traces et
références pseudonymisées.

- Branche : `feat/mlflow-integration-20261027`
- Base : `origin/main` `079317cd912168ec58ce4df377c49441cfc40186`
- SHA de code qualifié : `9d579e94f74d2758147fad44be23c72b5f4a41db`
  (le reçu JSON contient ce SHA ; un commit documentaire peut suivre sans
  changement de code).
- Version MLflow : `3.17.2` ; Python du serveur : `3.12.15`
- Serveur : `http://127.0.0.1:5000`, `--workers 1`, artefacts via MinIO
- Aucun secret n'est versionné. Les valeurs ne figurent pas dans ce document.

## 1. Architecture

```text
API/worker Arvor ──(client HTTP, auth basique)──> MLflow 127.0.0.1:5000
                                                     │
                                      ┌──────────────┴──────────────┐
                                      ▼                             ▼
                         PostgreSQL dédié `mlflow`       MinIO `mlflow-artifacts`
                         rôle `mlflow_app`               utilisateur dédié
```

Le serveur est lancé par `arvor-mlflow.service` (systemd utilisateur), pas par
une commande manuelle. Il tourne sous l'utilisateur WSL non privilégié, avec
`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`,
`PrivateTmp`, `MemoryDenyWriteExecute` et un seul répertoire inscriptible :
`~/.local/state/arvor-mlflow`.

Points d'isolation vérifiés :

- le rôle `mlflow_app` n'est pas superutilisateur, ne crée ni base ni rôle ;
- `CONNECT` sur la base métier `editorial` est refusé (contrôle réel) ; le
  provisioning révoque ce droit pour `mlflow_app`, et l'isolation effective
  est vérifiée par `has_database_privilege` **et** une tentative de connexion.
  Aucune révocation globale de `PUBLIC` n'est appliquée automatiquement :
  sur une autre installation, l'exploitant doit contrôler l'ACL réelle ;
- l'utilisateur MinIO MLflow ne peut pas lister le bucket métier
  `editorial-artifacts` (contrôle réel) ;
- le serveur n'écoute que sur `127.0.0.1:5000` ;
- l'authentification est obligatoire : `/health` sans identifiants renvoie 401.

## 2. Configuration (noms uniquement)

Fichiers locaux, hors dépôt, permissions `0600` :

| Fichier | Rôle |
| --- | --- |
| `~/.config/arvor-mlflow/mlflow.env` | configuration du serveur (backend PostgreSQL, S3, auth) |
| `~/.config/arvor-mlflow/client.env` | configuration du client Arvor (URI, identifiants, spool, délais) |
| `~/.config/arvor-mlflow/basic_auth.ini` | comptes du serveur MLflow |
| `~/.local/state/arvor-mlflow/secrets/` | mots de passe PostgreSQL, MinIO, auth et clé de session |

Variables lues par le tracker (aucune valeur par défaut secrète) :

| Variable | Effet |
| --- | --- |
| `ARVOR_MLFLOW_ENABLED` | `true` active l'envoi ; toute autre valeur le désactive |
| `MLFLOW_TRACKING_URI` | doit être un URI loopback explicite, avec port |
| `MLFLOW_TRACKING_USERNAME` / `MLFLOW_TRACKING_PASSWORD` | authentification du client, lue par MLflow depuis son environnement |
| `ARVOR_MLFLOW_SPOOL` | fichier de reprise borné (chemin absolu) |
| `ARVOR_MLFLOW_ENV_FILE` | charge explicitement le fichier client privé au démarrage (sinon télémétrie désactivée) |
| `ARVOR_CODE_VERSION` | SHA ou version reportée dans chaque run |
| `MLFLOW_HTTP_REQUEST_TIMEOUT` | délai court (3 s en exploitation locale) |
| `MLFLOW_HTTP_REQUEST_MAX_RETRIES` | réessais bornés (1 en exploitation locale) |
| `REQUESTS_CA_BUNDLE` / `AWS_CA_BUNDLE` | autorité TLS privée MinIO réutilisée pour les artefacts ; fichier régulier hors dépôt |
| `ARVOR_IMAGE_TIMEOUT_SECONDS` | délai sd.cpp, borné 30–600 s, défaut 300 s |

Le provisioning est idempotent :

```bash
python scripts/provision_mlflow_local.py --help
```

Il crée ou met à jour les ressources dédiées, sans modifier les bases, buckets,
volumes ou secrets métier. Il n'imprime que des noms et des booléens.

## 3. Instrumentation

Le module canonique est
`infrastructure/observability/mlflow_tracker.py`. Il n'utilise pas l'autolog :
les appels réels sont des clients HTTP (llama.cpp, sd.cpp, Piper, FFmpeg), donc
les traces sont créées manuellement, avec uniquement des empreintes, compteurs
et durées.

| Traitement | Point d'appel | Données envoyées |
| --- | --- | --- |
| Qwen (analyse, storyboard) | `editorial/service.py` | histoire, étape, version de prompt, SHA-256 du prompt et de la réponse, longueurs, tokens, modèle assaini, durée, statut, code d'erreur |
| Image sd.cpp | `editorial/media/application.py` | histoire, scène, modèle, version de prompt, seed, sampler, steps, CFG, scheduler, résolution, durée, statut, SHA-256 du PNG, octets, SHA-256 de la référence de stockage |
| Voix Piper | `production/voice_timeline.py` | histoire, moteur, voix, SHA-256 du WAV, octets, durée audio et cible, durée de génération, statut |
| Export FFmpeg | `scripts/render_episode.py` | histoire, nombre de scènes, durées cible/réelle, SHA-256 de la vidéo, octets, durée d'encodage, version FFmpeg, audio présent, résolution, FPS, profil, Ken Burns, transitions, sous-titres |
| Piste WAV existante | `record_export_receipt` | voix `external-wav`, SHA-256 du WAV, durée réelle |

Chaque événement porte un `arvor_event_id` déterministe (UUIDv5) construit à
partir de la clé métier et de l'empreinte. Une retransmission est donc reconnue
et ne crée pas de doublon. Les identifiants de tenant sont hachés ; les
identifiants d'histoire/scène/asset restent des UUID techniques.

Quatre expériences : `arvor-scenario-generation`, `arvor-image-generation`,
`arvor-voice-generation`, `arvor-video-generation`. Une expérience
`arvor-acceptance` et `arvor-health` servent aux contrôles locaux.

## 4. Confidentialité

- Aucun prompt, aucune réponse, aucune narration, aucun contenu de scène n'est
  envoyé : seuls les SHA-256, longueurs et compteurs le sont.
- Une liste d'autorisation refuse toute clé inconnue (`prompt`, `response`,
  `password`, `token`, etc.) avant l'envoi. Les traces ont leur propre liste
  fermée (`prompt_sha256`, `status`, `error_code`, `*_chars`, etc.) : une clé
  libre comme `narration` ou `content` fait rejeter l'événement entier.
- Les erreurs MLflow sont avalées : le tracker ne journalise ni URI complète, ni
  identifiant, ni secret.
- La recette scanne la base MLflow et les artefacts MinIO avec des marqueurs
  uniques insérés dans les prompts et vérifie qu'aucun n'apparaît.
- Aucun média n'est copié dans MLflow ; seules des références hachées le sont.
- La rétention est **manuelle** : aucune suppression automatique de preuve
  métier. Le contrôle mesure la taille de la base, le nombre d'expériences et
  d'objets MinIO sans les supprimer.

## 5. Panne, reprise et limites de charge

Le tracker est *fail-open* :

- file bornée de 64 événements ; au-delà, écriture dans un spool local borné
  (5 Mio pour le fichier actif, permissions `0600`, borne vérifiée sous verrou
  avant écriture) ; pendant un rejeu, le fichier réclamé et le nouveau fichier
  actif peuvent coexister, soit environ 10 Mio transitoires au maximum ;
- thread démon unique, aucun appel MLflow sur le chemin métier ;
- délai HTTP court et un seul réessai ;
- le worker inactif rejoue le spool une fois par minute ;
- rejeu manuel possible : `python scripts/mlflow_healthcheck.py --replay` ;
- le rejeu réclame le spool par renommage atomique, puis fusionne les échecs
  sous verrou inter-processus : un événement ajouté pendant le rejeu n'est
  jamais écrasé ;
- un rejeu est idempotent grâce à `arvor_event_id` ; la création est
  sérialisée dans le processus pour éviter deux runs pour le même événement ;
- une panne MLflow ne modifie ni l'entité, ni l'audit, ni l'outbox, ni le
  résultat d'une génération.

Limites assumées :

- le serveur MLflow consomme environ 1,7–1,8 Gio de mémoire avec un worker ;
- une génération sd.cpp peut dépasser deux minutes sur ce poste (mesure réelle :
  153 s) ; le délai par défaut a été porté à 300 s, paramétrable ;
- Piper est installé **localement hors dépôt** pour la recette ; l'image de
  production ne l'embarque pas encore. La chaîne WAV existante est, elle,
  instrumentée et testée ;
- le spool est un fichier local, non chiffré au repos, protégé par les
  permissions du compte et borné ; il ne contient que des données déjà
  pseudonymisées (jamais de prompt, réponse ou secret) ;
- les identifiants MLflow ne sont jamais recopiés dans `os.environ` par Arvor :
  le tracker lit l'environnement fourni au processus. Les sous-processus
  `piper`/`ffmpeg` reçoivent une copie filtrée par
  `infrastructure/process_env.py` (exclusion de `MLFLOW_*`, `ARVOR_MLFLOW_*`,
  `AWS_*`, `ARVOR_MINIO_*` et des secrets applicatifs), vérifiée par un test ;
- aucune rétention automatique ni purge n'est activée.

## 6. Exploitation

```bash
# état et démarrage automatique
systemctl --user status arvor-mlflow.service
systemctl --user restart arvor-mlflow.service

# santé (sans secret affiché)
python scripts/mlflow_healthcheck.py \
  --env-file ~/.config/arvor-mlflow/client.env --wait 30

# rejeu borné du spool
python scripts/mlflow_healthcheck.py \
  --env-file ~/.config/arvor-mlflow/client.env --replay

# installation / réinstallation du service
bash deploy/install_mlflow_service.sh
```

Prérequis : `loginctl enable-linger "$USER"` pour que le service utilisateur
démarre sans session ouverte. Après une coupure WSL, vérifier
`systemctl --user is-active arvor-mlflow.service` et le healthcheck.

Le journal ne doit jamais être copié dans un ticket sans vérification : il peut
contenir des identifiants de runs, jamais de secret applicatif.

## 7. Recette réelle du 27 octobre 2026

Exécution : `scripts/mlflow_acceptance.py`, avec Qwen réel
(`172.31.48.1:8081`), sd.cpp réel (`172.31.48.1:8082`), FFmpeg 8.0.1 et Piper
`fr_FR-siwis-medium`. Trois exécutions complètes ont réussi : avant la revue
indépendante (`109e5cc`), après le premier durcissement (`26a4547`), puis après
les correctifs résiduels (`9d579e94`). Le reçu final est conservé hors dépôt :
`/tmp/opencode/mlflow-acceptance-final-9d579e94.json`. Le tableau ci-dessous
reprend les preuves de cette exécution finale qualifiée.

15 contrôles réussis, 0 échec à chaque exécution :

| Contrôle | Preuve |
| --- | --- |
| service systemd actif et `enabled` | `active`, `enabled`, redémarrage propre |
| loopback seul | `127.0.0.1:5000` |
| authentification obligatoire | anonyme 401, authentifié 200 |
| PostgreSQL dédié | `current_user=mlflow_app` |
| isolation base métier | `CONNECT` refusé sur `editorial` |
| persistance après redémarrage | paramètre relu après `stop/start` |
| artefact MinIO + isolation | aller-retour OK, bucket métier refusé |
| Qwen réel + trace | run `72e50e1527d14f669949e7c2a023cfa3`, trace `tr-042b7a44479b747271c5abea75883ebe`, span `arvor.scenario.analysis` |
| comparaison de deux runs | même SHA de prompt, tokens/durées distincts, deux runs comparables |
| image réelle | run `74eafb3c4c134bbc8e3854d299a45274`, 512×512, 153,45 s, SHA-256 `5f29c9d4…4c6e9f` |
| voix Piper réelle | run `d0357bf807d14c79a324e58486a38726`, 75 s, SHA-256 `883178eb…da0c3a` |
| vidéo 75 s + audio | run `895d8908e0cf4925900b77fc5c049398`, 75 s, audio présent, SHA-256 `b84feedf…3791d4`, voix `c5b731fd…0c32eb` |
| panne MLflow | soumission 0,0002 s, spool puis rejeu `replayed=1`, un seul run (`b375c12a…79bbd0ba`) |
| absence de fuite | 4 marqueurs et 4 secrets recherchés, 0 correspondance en base et dans les artefacts |
| empreinte bornée | base 12,49 Mo, 7 expériences, 22 objets, 8 723 octets d'artefacts, mémoire 1,75 Gio |
| bucket métier intact | 4 objets métier toujours présents |

La vidéo de recette contient une piste audio Piper réelle et un WAV de 75 s
instrumenté comme `external-wav`. Les fichiers de recette restent sous
`/tmp/opencode/mlflow-acceptance-*` et ne sont pas versionnés.

### 7.1 Qualification CI locale (28 octobre 2026)

Le laboratoire CI isolé a été exécuté sur le SHA de tête
`bf293a12eacd764b0784e6587d70ffcb17793aab`, base
`079317cd912168ec58ce4df377c49441cfc40186`, PR #225, contrôleur épinglé sur la
même base `main`. Image Docker épinglée :
`sha256:dd7076aba086afc2bd9439544fab0d9f48989b3070636323719b11c4cd0c082e`.
Reçu privé : `run_id 1322464b-c2e5-4966-839e-193789412fb4` ; provenance hôte et
intégrité des journaux vérifiées indépendamment. Ce reçu ne signe ni ne publie
rien et n'autorise ni fusion ni déploiement.

16/16 contrôles réussis :

| Contrôle | Résultat |
| --- | --- |
| `db_prepare_312`, `db_prepare_314` | PostgreSQL 16 jetable préparé |
| `regression_312`, `regression_314` | 531 tests, 0 échec, 0 ignoré par version Python |
| `sql_benchmark_312`, `sql_benchmark_314` | benchmark éditorial 1 200 runs |
| `syntax_js`, `syntax_js_reference`, `syntax_js_next`, `syntax_py` | syntaxe valide |
| `browser` | 18 parcours Chromium, 0 échec, 0 ignoré |
| `dependencies` | audit hors ligne des dépendances installées |
| `secrets` | Gitleaks, aucun secret détecté |
| `supply_chain` | empreintes de dépendances conformes |
| `risk_review` | revue de risques du diff |
| `video_75` | smoke vidéo synthétique 75 s |

Les contrôles navigateur, Gitleaks, Node et l'audit précédemment absents du
poste ont donc été exécutés dans le conteneur isolé, sans installation dans le
dépôt ni dans le runtime déployé.

### 7.2 Recette épisode Ys et prototype (28 octobre 2026)

Deux histoires réelles ont été générées dans une base PostgreSQL jetable
(`episode_ys_20261028`) et un stockage fichiers isolé, sans toucher au runtime
déployé ni aux bases métier :

| Histoire | Rôle | Scènes | Durée | Runs MLflow |
| --- | --- | --- | --- | --- |
| `be520301-a010-595e-8b6c-840c340924aa` | épisode final | 5 | 75 s | 2 scénario + 5 images + 1 voix + 2 exports (1 rejeté, 1 accepté) |
| `875b28c0-38f4-5619-af78-8f7a840832ad` | prototype cohérence | 3 | 45 s | 2 scénario + 3 images + 1 voix + 2 exports (1 rejeté, 1 accepté) |

Paramètres réellement enregistrés : Qwen `qwen2.5-3b-instruct-q4_k_m.gguf`,
prompt `1.2.0`, `temperature=0.1`, `max_tokens=2048` ; sd.cpp
`sd-cpp-local`, prompt `2.0.0`, 512×512, `euler_a`, 20 steps, CFG 7.0,
scheduler `discrete`, seed déterministe par `scene_id` (par exemple
`1342130966`) ; Piper `fr_FR-siwis-medium.onnx` ; export 1080×1920, 24 fps,
H.264/AAC, Ken Burns, fond flou, fondus 0,5 s, sous-titres incrustés et SRT
latéral. Les SHA-256 des médias et les durées de génération sont dans le rapport
`docs/P0_EPISODE_YS_20261028.md`.

Contrôles P0-A :

- rechargement de `~/.config/arvor-mlflow/client.env` avec certificat MinIO
  existant : `healthy=true`, `artifact_roundtrip=true`, 8 expériences, 3,58 s ;
- test de panne réel (URI morte puis rétablie) : premier rejeu
  `replayed=1`, second `replayed=0`, un seul run créé, aucun prompt/réponse dans
  le spool ;
- les 8 médias et les 11 runs ont survécu au redémarrage de l'API isolée ;
- les deux exports rejetés sont conservés avec le tag
  `arvor_validation_status=superseded` et leur motif ; l'export accepté porte
  `technical_accepted`, `arvor_validator=open-code-operator` et
  `arvor_independent_validation=pending`.

Limites de cette recette : l'API déployée sur `127.0.0.1:8000` n'a pas été
modifiée et n'était pas configurée pour MLflow ; la télémétrie a été prouvée
dans un processus isolé (`ARVOR_MLFLOW_ENV_FILE`). Les images de l'épisode ont
été générées avant l'étiquette `sd-cpp-local` et la version de prompt image :
leurs runs portent encore `sd.cpp-compatible`, sans `prompt_version` image. Le
prototype, généré après, porte les deux. Aucune revue humaine indépendante ni
validation métier n'a encore été enregistrée.

## 8. Revue indépendante et corrections

Une revue `security-reviewer` en lecture seule a été exécutée après la première
recette. Aucun constat bloquant. Les constats majeurs et mineurs retenus ont été
corrigés avant la recette finale (dix correctifs au total) :

| Constat | Correction |
| --- | --- |
| le mot de passe MLflow pouvait être recopié dans `os.environ`, donc hérité par `ffmpeg`/`piper` | suppression de la recopie et des variantes `*_FILE` ; MLflow lit ses identifiants dans l'environnement fourni au processus |
| deux publieurs pouvaient créer le même run (recherche puis création non atomiques) | verrou de publication dans le processus ; limite multi-processus documentée |
| un rejeu pouvait écraser une ligne ajoutée pendant la lecture | réclamation atomique par renommage, verrou inter-processus, fusion des échecs |
| borne du spool non stricte | taille projetée vérifiée sous verrou avant écriture |
| les traces acceptaient des clés libres | liste fermée `TRACE_KEYS`, rejet de l'événement hors liste |
| la télémétrie d'export était dans le bloc qui supprime un export en échec | appel déplacé hors du bloc protégé |
| `write_private` suivait un lien symbolique | `O_NOFOLLOW` ajouté, répertoire forcé en `0700`, `fsync` avant remplacement |
| un spool UTF-8 corrompu pouvait tuer le thread de télémétrie | lecture protégée, fichier brut restauré, rejeu gardé par `except BaseException` |
| `trace.name` restait un canal libre | motif fermé `arvor.<kind>...`, rejet sinon |
| le verrou du spool suivait un lien | ouverture du verrou avec `O_NOFOLLOW` |

Une seconde revue ciblée, après qualification CI, a porté sur le diff complet
et l'exploitation réelle. Aucun constat bloquant ; trois correctifs et une
clarification ont été appliqués :

| Constat | Correction |
| --- | --- |
| `piper`/`ffmpeg` héritaient des variables `MLFLOW_*` si l'opérateur les avait chargées dans le processus | environnement enfant filtré par `infrastructure/process_env.py`, appliqué aux deux chaînes de sous-processus et couvert par un test |
| le spool était ouvert sans `O_NOFOLLOW` | refus d'un lien symbolique et `O_NOFOLLOW` sur les deux écritures |
| le faux client de test ignorait le filtre `arvor_event_id`, donc une régression d'idempotence pouvait passer | filtre réellement appliqué, tag et filtre vérifiés, cas de deux événements distincts ajouté |
| la révocation `CONNECT` du seul rôle applicatif ne couvre pas une ACL `PUBLIC` héritée sur une autre installation | limite explicitée ; la recette vérifie `has_database_privilege` et une connexion réelle |

Risques résiduels acceptés et documentés : la déduplication reste locale au
processus (deux processus distincts peuvent rarement créer deux runs pour un
même événement) ; l'écriture du spool reste synchrone lorsqu'une file pleine
déborde (latence bornée) ; pendant un rejeu, le spool peut occuper jusqu'à
environ 10 Mio (fichier réclamé + nouveau fichier actif) ; l'outil de recette
utilise les identifiants MinIO racine pour vérifier, sans les imprimer, que le
bucket métier est intact. La tête finale de la branche a été requalifiée
16/16 après ces correctifs ; le reçu correspondant est référencé dans la
PR #225.

## 9. Ce qui reste hors périmètre

- Fusion de la PR #225 et déploiement PC : non réalisés, à valider séparément
  sur le SHA complet.
- Activation MLflow dans le service API déployé : le runtime
  `~/editorial-runtime/current` n'a pas été modifié.
- Embarquement de Piper dans l'image applicative.
- Rétention automatique, purge, tableau de bord ou alerting MLflow.

Toute activation en production exige une livraison PC approuvée sur un SHA
complet exact, puis un redémarrage contrôlé du service API avec la configuration
`client.env`. Aucune de ces opérations n'a été effectuée ici.
