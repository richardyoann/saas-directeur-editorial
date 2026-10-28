# Production média 75 s — voix, vidéo et sous-titres

Statut au 28 octobre 2026 : **développé et testé localement**, pas encore
qualifié en CI ni déployé. Ce document décrit le comportement réel du code de
la branche `feat/mvp-video-75-20261028`, pas une cible.

## 1. Périmètre

Depuis un storyboard **approuvé** de 75 secondes et ses images prêtes, le Studio
peut produire, dans cet ordre :

1. une narration Piper de 75 secondes (`POST /editorial/runs/{id}/voice`) ;
2. un montage vertical 720×1280 avec audio et sous-titres
   (`POST /editorial/runs/{id}/video`).

Les fichiers sont stockés dans le stockage privé existant (système de fichiers
ou MinIO), décrits en base PostgreSQL et consultables dans l'onglet
« Voix & vidéo » du Studio. PostgreSQL reste la source de vérité ; aucun média
n'est dupliqué dans MLflow.

## 2. Prérequis et refus explicites

| Condition | Comportement |
| --- | --- |
| storyboard non approuvé ou obsolète | 409 `approval_required` |
| durée cumulée différente de 75 s | 409 `storyboard_duration_invalid` |
| PiPER/FFmpeg non configurés | 503 `voice_provider_unconfigured` / `video_provider_unconfigured` |
| image manquante ou voix absente au montage | 409 `media_incomplete` |
| une seule production média en cours | 429 `media_capacity_busy` avec `Retry-After: 30` |
| média déjà prêt ou réservation concurrente | 409, aucun écrasement |
| échec de synthèse ou de montage | 502, erreur historisée, **aucun rejeu automatique** |
| panne de stockage ou de base | 503, aucun média partiel publié |

Une relance n'est possible qu'après un échec. Un média prêt est immuable : une
nouvelle réservation est refusée. Une révision du storyboard produit un nouveau
`scenario_id`, donc de nouveaux identifiants de médias ; l'ancien reste
consultable.

## 3. Contrat HTTP

Routes privées, jeton Bearer obligatoire, préfixe `/editorial` côté API et
`/studio/api` côté proxy Studio :

- `GET /runs/{run_id}/production-media` : état approuvé, durée, images
  manquantes, statut et identifiants des médias, capacités ;
- `POST /runs/{run_id}/voice` : synthèse et publication de la voix ;
- `POST /runs/{run_id}/video` : montage, sous-titres et publication ;
- `GET /runs/{run_id}/media/{media_id}/content` : lecture privée ;
  `?download=1` ajoute un nom de fichier borné `arvor-<type>-<8 car.>.<ext>`.

Réponses et erreurs ne contiennent jamais de chemin de stockage, de clé MinIO,
de secret, de prompt ou de commande exécutée. Les en-têtes de contenu valent
`Cache-Control: no-store` et `X-Content-Type-Options: nosniff`.

## 4. Identifiants déterministes et concurrence

Les identifiants sont calculés avec `uuid5` :

- voix : `uuid5(scenario_id, "production-voice-v1")` ;
- vidéo : `uuid5(scenario_id, "production-video-v1")` ;
- sous-titres : `uuid5(scenario_id, "production-subtitles-v1")`.

La réservation verrouille la ligne du run puis la ligne de l'actif, dans le même
ordre que les images et la revue humaine. La publication de la vidéo et des
sous-titres est atomique. Chaque écriture produit une entrée d'audit et une
entrée d'outbox dans la même transaction. La capacité média est partagée entre
voix et vidéo : une seule production à la fois, dans le processus.

## 5. Stockage et intégrité

- Écriture exclusive (`O_CREAT|O_EXCL`, `O_NOFOLLOW` si disponible, mode 0600),
  jamais d'écrasement.
- Lecture après revalidation : type, locataire, run, identifiant, taille,
  empreinte SHA-256, refus des liens symboliques sur le chemin.
- Les images relues utilisent l'identifiant de scène, pas l'identifiant d'actif,
  car c'est la clé réellement écrite par la chaîne image.
- Les médias prêts ne sont référencés que par identifiant ; le chemin ou la clé
  reste côté serveur.

## 6. Configuration (noms uniquement)

| Variable | Rôle |
| --- | --- |
| `ARVOR_PIPER_BIN` | binaire Piper (défaut `piper`) |
| `ARVOR_PIPER_MODEL` | modèle `.onnx` local, obligatoire pour la voix |
| `ARVOR_FFMPEG_BIN` | binaire FFmpeg utilisé pour la voix (défaut `ffmpeg`) ; le montage résout `ffmpeg` et `ffprobe` dans `PATH` |
| `ARVOR_MEDIA_WORK_DIR` | répertoire de travail privé ; à défaut le temporaire système |
| `EDITORIAL_MEDIA_BACKEND` | `filesystem` ou `minio` |
| `EDITORIAL_MEDIA_ROOT` | racine privée du backend fichiers |
| `MEDIA_S3_*` | configuration MinIO existante, inchangée |

Aucun outil n'est téléchargé ni installé au démarrage.

## 7. Interface Studio

Onglet « Voix & vidéo » : liste de contrôle (scénario approuvé, 75 s, images,
voix, vidéo), boutons explicites, avertissements sur les images manquantes,
lecteur audio, lecteur vidéo vertical, liens de téléchargement WAV/MP4/SRT.
Les états « en cours » découragent le double clic ; les erreurs sont affichées
sans détail technique.

## 8. Tests

- `tests/test_production_media.py` : cas d'usage, prérequis, capacité,
  échecs sans rejeu, télémétrie, lecture temporaire.
- `tests/test_production_media_postgres.py` : PostgreSQL réel jetable
  (réservation, conflits, isolation locataire, audit/outbox, atomicité,
  sous-titres, scénario obsolète).
- `tests/test_production_media_storage.py` : écriture exclusive, permissions,
  intégrité, liens symboliques, images, backend inconnu.
- `tests/test_production_media_api.py` : authentification, codes 404/409/429/502/
  503, en-têtes, nom de téléchargement, nettoyage après envoi.
- `browser_checks/test_studio_browser.py` : parcours navigateur réel voix puis
  vidéo, avec API factice isolée (aucune donnée utilisateur).

## 9. Limites connues

- Le proxy Studio charge le média en mémoire et refuse au-delà de 128 Mio. Un
  montage 75 s reste très en dessous ; une diffusion de gros fichiers exigerait
  un relais en flux.
- Une seule production média par processus : suffisant pour un worker unique,
  à revoir avant montée en charge.
- Piper et FFmpeg ne sont pas embarqués dans l'image API.
- Les sous-titres sont produits par le rendu existant ; aucune synchronisation
  avancée ni correction manuelle n'est proposée.
- La qualité éditoriale et visuelle reste soumise à relecture humaine ; aucun
  score automatique n'est revendiqué.
- Aucune livraison PC : l'activation exige une approbation explicite du SHA
  complet et une recette sur le poste.
