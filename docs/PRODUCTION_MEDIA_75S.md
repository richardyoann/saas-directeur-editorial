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

Une relance n'est possible qu'après un échec. La réservation et toute la phase
post-réservation (synthèse, écriture, publication) s'exécutent dans le même fil
de travail : une annulation de requête ne peut pas laisser une ligne
`generating`. Un échec ferme la réservation par `failed` ; si la base est
indisponible au point de rendre cette clôture impossible, la réservation
orpheline est clôturée (`media_reservation_expired`) puis reprise
automatiquement **après une heure**, délai très supérieur à la plus longue
synthèse. Le nombre de tentatives est borné à 1 000. Le dossier de travail privé
est validé **avant** la réservation. Un média prêt est immuable : une nouvelle
réservation est refusée. Une révision du storyboard
produit un nouveau `scenario_id`, donc de nouveaux identifiants de médias ;
l'ancien reste consultable.

Après un échec, la relance réserve une nouvelle tentative (`attempt` incrémenté)
et écrit une **clé de stockage distincte et immuable** : l'objet de la tentative
échouée reste orphelin, ne bloque plus la relance et n'est jamais écrasé. Dans
une même tentative, un accusé de réception perdu n'est réutilisé que si l'objet
stocké a la même taille et le même SHA-256 ; sinon l'upload reste incertain et
rien n'est supprimé ni écrasé.

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

- Écriture atomique : fichier temporaire privé dans le même répertoire, puis
  lien exclusif vers la destination (`O_EXCL`/`O_NOFOLLOW` si disponible, mode
  0600), jamais d'écrasement. La clé contient la tentative (`attempt`) :
  `attempt=1` garde le nom historique, une relance écrit `-a2`, `-a3`, etc.
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
  échecs sans rejeu, fermeture de réservation après échec de publication,
  validation du dossier avant réservation, télémétrie, lecture temporaire.
- `tests/test_production_media_postgres.py` : PostgreSQL réel jetable
  (réservation, conflits, isolation locataire, reprise d'une réservation
  orpheline après le bail, audit/outbox, atomicité, sous-titres, scénario
  obsolète).
- `tests/test_production_media_storage.py` : écriture exclusive, permissions,
  intégrité, liens symboliques, images, backend inconnu, clés par tentative et
  relance après échec.
- `tests/test_production_media_api.py` : authentification, codes 404/409/429/502/
  503, en-têtes, nom de téléchargement, nettoyage après envoi.
- `browser_checks/test_studio_browser.py` : parcours navigateur réel voix puis
  vidéo, avec API factice isolée (aucune donnée utilisateur).

## 9. Recette réelle du 28 octobre 2026

Réalisée sur le code du SHA `262689c16215aa7fd3240578169aa2269bb834be`
(les commits de documentation postérieurs ne modifient aucun fichier exécuté),
avec PostgreSQL 16 et MinIO jetables, un bucket et un utilisateur S3 dédiés,
TLS vérifié par la CA locale et une seule instance API. Aucune base, aucun
bucket, aucun volume ni secret métier utilisés. 15 contrôles réussis.

| Contrôle | Résultat mesuré |
| --- | --- |
| préparation jetable | base `acceptance`, bucket dédié `arvor-acceptance-<suffixe>`, utilisateur S3 à privilèges limités |
| run approuvé | 3 scènes, 75 s cumulées, storyboard approuvé |
| images | 3 PNG stockés dans MinIO, empreinte `5f29c9d43b35b281dc3e70eabef7de9bb89161ab88e02fa6e59e18f4074c6e9f`, 614 251 octets |
| plan avant voix | approuvé, voix possible, images complètes, vidéo non prête |
| voix Piper via HTTP | 200, 75,000 s, 24 000 Hz, mono, 3 600 044 octets, SHA-256 `9aa7671ccd81ee30169487ee7fc2b482f8cc8b9d05d4ac383368d6ff41d4c926` |
| vidéo FFmpeg via HTTP | 200, H.264 720×1280 + AAC, 75,000 s, 2 581 258 octets, SHA-256 `97280b7745c4520565b6d784cb906fa6db6441cbfa86a1601f2ac452cb6f0e7b` |
| sous-titres | 3 repères, dernier à 75,0 s, 275 octets, téléchargement `.srt` |
| refus | 401 sans jeton et avec mauvais jeton, 404 média/run inconnus, 409 voix et vidéo déjà prêtes |
| fuite | 0 correspondance sur 8 marqueurs (bucket, chemins, outils, jeton, modèle) |
| PostgreSQL | 3 médias `ready` avec empreintes conformes, audit et outbox atomiques pour chaque actif |
| MinIO | 6 objets (3 PNG, 1 WAV, 1 MP4, 1 SRT), tailles non nulles |
| relance et tentative | clés `attempt=1` et `attempt=2` distinctes sur MinIO, relecture des octets de la tentative 2, réutilisation d'un upload identique, tentative falsifiée refusée |
| durées | voix 5,6 s, montage 8,3 s |

Limites de cette recette : le moteur sd.cpp n'était pas joignable au moment de
la recette ; les images utilisées sont de vraies sorties sd.cpp générées le
27 octobre 2026 sur le PC (même empreinte que la recette MLflow) et injectées
par le cas d'usage image réel. La génération d'images en direct n'est donc pas
rejouée ici ; elle a été acceptée séparément. La voix et le montage ont été
réellement produits pendant la recette. Aucun déploiement PC n'a eu lieu.

Chaque exécution produit des octets différents (Piper et FFmpeg ne sont pas
reproductibles au bit près) : les empreintes ci-dessus valent pour cette
exécution et ne servent pas de référence fonctionnelle.

## 10. Limites connues

- Le proxy Studio charge le média en mémoire et refuse au-delà de 128 Mio. Un
  montage 75 s reste très en dessous ; une diffusion de gros fichiers exigerait
  un relais en flux.
- Une seule production média par processus, sans limitation de débit : un
  locataire authentifié peut monopoliser la capacité jusqu'à la fin de sa
  synthèse. Suffisant pour un worker unique, à revoir avant montée en charge.
- Les objets des tentatives échouées restent orphelins dans le stockage privé
  (aucune suppression autorisée) ; ils ne sont ni référencés ni lisibles par
  l'API. Un nettoyage manuel contrôlé reste à définir.
- Une réservation orpheline n'est reprise qu'après une heure : c'est le prix de
  la sécurité face à une synthèse encore en cours, sans démon de redémarrage.
- Le relais Studio matérialise une copie temporaire pour la lecture ; le
  nettoyage est déclenché en fin de réponse, un client qui coupe brutalement
  peut laisser un fichier temporaire jusqu'au prochain nettoyage système.
- Piper et FFmpeg ne sont pas embarqués dans l'image API.
- Les sous-titres sont produits par le rendu existant ; aucune synchronisation
  avancée ni correction manuelle n'est proposée.
- La qualité éditoriale et visuelle reste soumise à relecture humaine ; aucun
  score automatique n'est revendiqué.
- Aucune livraison PC : l'activation exige une approbation explicite du SHA
  complet et une recette sur le poste.
