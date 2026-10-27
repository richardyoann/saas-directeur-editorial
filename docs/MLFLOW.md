# MLflow privé Arvor — intégration, exploitation et preuves

Statut au 27 octobre 2026 : **qualifié localement sur WSL**, non poussé, non
fusionné et **non déployé sur le PC**. Le serveur MLflow est un service
utilisateur systemd privé, sur loopback, avec PostgreSQL et MinIO dédiés.
PostgreSQL Arvor reste la source de vérité métier ; MLflow ne contient que des
expériences, mesures, traces et références pseudonymisées.

- Branche : `feat/mlflow-integration-20261027`
- Base : `origin/main` `079317cd912168ec58ce4df377c49441cfc40186`
- SHA de code qualifié : reporté dans la section « Preuves de recette » après
  le commit de qualification (le reçu JSON contient le SHA complet).
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
- `CONNECT` sur la base métier `editorial` est refusé (contrôle réel) ;
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
| `ARVOR_CODE_VERSION` | SHA ou version reportée dans chaque run |
| `MLFLOW_HTTP_REQUEST_TIMEOUT` | délai court (3 s en exploitation locale) |
| `MLFLOW_HTTP_REQUEST_MAX_RETRIES` | réessais bornés (1 en exploitation locale) |
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
| Image sd.cpp | `editorial/media/application.py` | histoire, scène, modèle, résolution, durée, statut, SHA-256 du PNG, octets, SHA-256 de la référence de stockage |
| Voix Piper | `production/voice_timeline.py` | histoire, moteur, voix, SHA-256 du WAV, octets, durée audio et cible, durée de génération, statut |
| Export FFmpeg | `scripts/render_episode.py` | histoire, nombre de scènes, durées cible/réelle, SHA-256 de la vidéo, octets, durée d'encodage, version FFmpeg, audio présent, résolution, FPS |
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
  (5 Mio, permissions `0600`, borne vérifiée sous verrou avant écriture) ;
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
  ils restent dans l'environnement fourni au processus, et les sous-processus
  `ffmpeg`/`piper` ne les reçoivent pas par cette voie ;
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
`fr_FR-siwis-medium`. Rapport JSON conservé hors dépôt :
`/tmp/opencode/mlflow-acceptance-report.json`.

15 contrôles réussis, 0 échec :

| Contrôle | Preuve |
| --- | --- |
| service systemd actif et `enabled` | `active`, `enabled`, redémarrage propre |
| loopback seul | `127.0.0.1:5000` |
| authentification obligatoire | anonyme 401, authentifié 200 |
| PostgreSQL dédié | `current_user=mlflow_app` |
| isolation base métier | `CONNECT` refusé sur `editorial` |
| persistance après redémarrage | paramètre relu après `stop/start` |
| artefact MinIO + isolation | aller-retour OK, bucket métier refusé |
| Qwen réel + trace | run `a4db762e55e841de98fff633be400a8f`, trace `tr-dbc0383a8d5a4a75d0d2f39229112f20`, span `arvor.scenario.analysis` |
| comparaison de deux runs | `50b5bcf1430245138e3141c4b4ae798c` et `c1eab3e80e624bc08e347908bd129620`, même SHA de prompt, tokens/durées distincts |
| image réelle | run `3f1b1d11fb7641ccb2e576a50b87058f`, 512×512, 153,29 s, SHA-256 `783e9e70…e84702` |
| voix Piper réelle | run `d205caaba1f54e108a3765ccf259274f`, 75 s, SHA-256 `6543f5ac…924a2d` |
| vidéo 75 s + audio | run `6230fe4171694bd1a3181ccc578bdf64`, 75 s, audio présent, SHA-256 `deb3705f…58e0d1` |
| panne MLflow | soumission 0,0003 s, spool puis rejeu `replayed=1`, un seul run |
| absence de fuite | 4 marqueurs et 4 secrets recherchés, 0 correspondance en base et dans les artefacts |
| empreinte bornée | base 11,99 Mo, 7 expériences, 16 objets, 6 273 octets d'artefacts, mémoire 1,75 Gio |
| bucket métier intact | 4 objets métier toujours présents |

La vidéo de recette contient une piste audio Piper réelle et un WAV de 75 s
instrumenté comme `external-wav`. Les fichiers de recette restent sous
`/tmp/opencode/mlflow-acceptance-*` et ne sont pas versionnés.

## 8. Revue indépendante et corrections

Une revue `security-reviewer` en lecture seule a été exécutée après la première
recette. Aucun constat bloquant. Les constats majeurs et mineurs retenus ont été
corrigés avant la recette finale :

| Constat | Correction |
| --- | --- |
| le mot de passe MLflow pouvait être recopié dans `os.environ`, donc hérité par `ffmpeg`/`piper` | suppression de la recopie et des variantes `*_FILE` ; MLflow lit ses identifiants dans l'environnement fourni au processus |
| deux publieurs pouvaient créer le même run (recherche puis création non atomiques) | verrou de publication dans le processus ; limite multi-processus documentée |
| un rejeu pouvait écraser une ligne ajoutée pendant la lecture | réclamation atomique par renommage, verrou inter-processus, fusion des échecs |
| borne du spool non stricte | taille projetée vérifiée sous verrou avant écriture |
| les traces acceptaient des clés libres | liste fermée `TRACE_KEYS`, rejet de l'événement hors liste |
| la télémétrie d'export était dans le bloc qui supprime un export en échec | appel déplacé hors du bloc protégé |
| `write_private` suivait un lien symbolique | `O_NOFOLLOW` ajouté |

Risques résiduels acceptés et documentés : la déduplication reste locale au
processus (deux processus distincts peuvent rarement créer deux runs pour un
même événement) ; l'écriture du spool reste synchrone lorsqu'une file pleine
déborde (latence bornée) ; l'outil de recette utilise les identifiants MinIO
racine pour vérifier, sans les imprimer, que le bucket métier est intact.

## 9. Ce qui reste hors périmètre

- Push, PR, fusion et déploiement PC : non réalisés, à valider séparément sur
  le SHA complet.
- Activation MLflow dans le service API déployé : le runtime
  `~/editorial-runtime/current` n'a pas été modifié.
- Embarquement de Piper dans l'image applicative.
- Rétention automatique, purge, tableau de bord ou alerting MLflow.
- Recette navigateur Playwright : binaires Chromium absents sur ce poste.

Toute activation en production exige une livraison PC approuvée sur un SHA
complet exact, puis un redémarrage contrôlé du service API avec la configuration
`client.env`. Aucune de ces opérations n'a été effectuée ici.
