# MEDIA-004 — stockage privé des médias dans MinIO

16 octobre 2026. Base de développement : `517a62dc3a7077f9b82e9ca82d2cfcb224899ae4`.

## Constat et changement

Le Compose déclarait déjà MinIO, mais le code écrivait les PNG uniquement dans
`EDITORIAL_MEDIA_ROOT`. Le nouveau backend est optionnel : aucune donnée ni
configuration du PC n'est déplacée ou activée par cette PR.

Les nouvelles images peuvent être stockées en objets privés ; PostgreSQL garde
bucket, clé opaque tenant/run/asset, version éventuelle, taille et SHA-256.
Le statut ready, la référence, l'audit et l'outbox sont validés dans la même
transaction SQL. L'objet S3 et SQL ne forment pas une transaction distribuée :
un échec après transfert laisse un objet à réconcilier, jamais supprimé
automatiquement. Une référence absente conserve la lecture historique sur disque.
Une référence MinIO persiste même si le backend de nouvelles écritures est
repassé à filesystem : garder les identifiants S3 pour lire ces anciens objets.

## Configuration après validation de la release exacte

Installer les dépendances versionnées de `requirements.txt` (Boto3 1.40.0).
La CI et le script de livraison existants lisent déjà ce manifeste : aucune
nouvelle installation de service ou modification de Compose n'est nécessaire.
Le bucket doit préexister et être privé. Créer un compte applicatif avec
ListBucket, GetObject, GetObjectVersion et PutObject limités à ce bucket ;
ne pas utiliser les identifiants root d'exemple du Compose en exploitation.
Aucun droit DeleteObject ou modification de politique n'est nécessaire.

```dotenv
EDITORIAL_MEDIA_BACKEND=minio
MEDIA_S3_ENDPOINT=http://127.0.0.1:9000
MEDIA_S3_BUCKET=editorial-media
MEDIA_S3_ACCESS_KEY=
MEDIA_S3_SECRET_KEY=
EDITORIAL_MEDIA_ROOT=/chemin/prive/recovery-media
```

Fournir les vrais secrets uniquement dans l'environnement privé du service.
L'endpoint doit être localhost ou une adresse IP privée autorisée ; aucune URL
publique, aucun identifiant dans une URL et aucun proxy implicite.
Pour une liaison entre machines, fournir HTTPS avec certificat valide.
Les buckets ne sont pas créés, rendus publics ou reconfigurés par le code.
Le support de PUT conditionnel `If-None-Match: *` doit être testé sur la version
MinIO installée : une incompatibilité échoue sans écrasement de remplacement.

## Images

Le preflight vérifie le bucket et le dossier local de secours avant génération.
Le PNG généré reste sur disque pendant le transfert, puis est retiré après
acquittement et contrôle HEAD taille/empreinte. Sur transfert incertain, le PNG
est conservé et le résultat marqué incertain, sans nouveau rendu ni retry.
Les lectures passent par l'API authentifiée existante, pas par une URL publique.
Elles téléchargent un temporaire borné et vérifient SHA-256 et taille avant
de rendre le PNG. Aucun cache durable supplémentaire n'est créé.

## Voix, images et vidéo d'un dossier de production

Les moteurs de voix et le montage continuent à travailler sur des fichiers
locaux. Après export et approbation de l'histoire, dans un shell configuré
avec les UUID tenant/acteur et PO_DATABASE_URL du service privé :

```bash
python scripts/archive_episode.py /dossier/prive/episode-export --run-id UUID_DU_RUN
```

La CLI archive `episode.mp4`, `voice.wav`, `scene-1.png` à `scene-6.png`,
`narration.srt`, `production.json`, `receipt.json` lorsqu'ils sont présents.
Chaque objet a un UUID neuf ; sa référence est enregistrée avec audit/outbox
sur le run approuvé. Maximum 1 Gio par fichier ; uploads séquentiels, lecture
par blocs, une seule tentative réseau. Les fichiers ne sont ni générés ni
modifiés et les fichiers inconnus ne sont pas archivés.

Le journal privé `minio-archive.jsonl` est créé exclusivement : started avant
PUT, stored avant SQL, recorded après SQL. Une seconde invocation est refusée
si ce journal existe, pour imposer une réconciliation des cas ambigus.

Pour restaurer dans un **nouveau** dossier local :

```bash
python scripts/restore_episode_media.py /dossier/prive/episode-export/minio-archive.jsonl /dossier/prive/restauration-test --run-id UUID_DU_RUN
```

Chaque fichier est vérifié par taille/SHA-256 et les clés sont contraintes
au tenant/run/asset attendu. Un journal incomplet doit être réconcilié avant
restauration. Les sources restent présentes après archivage : aucune économie
d'espace effective n'est annoncée tant que restauration et sauvegarde ne sont
pas vérifiées et qu'un nettoyage explicite n'est pas réalisé.

## Performance, reprise et preuves

MinIO centralise la conservation. Cela ne réduit pas automatiquement le temps
de génération ou la taille des médias : transferts et empreintes ajoutent du
travail. FFmpeg reste local. Mesurer temps de rendu/transfert et occupation
avant/après sur les mêmes médias ; aucun gain chiffré n'est annoncé.

Les tests couvrent S3 simulé, paramètres du vrai SDK, contrôle d'intégrité,
absence de retry, récupération après timeout, compatibilité disque et écriture
PostgreSQL auditée. Une CI verte n'est pas un test du MinIO du PC.
La recette réelle exige un upload/download PNG/WAV/MP4, refus d'écrasement,
lecture Studio, restauration et contrôle du journal sur le SHA livré.

Retour arrière : remettre filesystem pour les nouvelles images, conserver
les objets et leurs identifiants pour les lectures existantes. Aucun ALTER SQL
ni migration des fichiers historiques. Conserver les volumes MinIO et des
sauvegardes sur un support indépendant ; MinIO sur le même disque n'est pas
une sauvegarde indépendante. Lire [reprise](mco/MINIO_MEDIA_RECOVERY.md).

Référence du contrat S3 :
https://boto3.amazonaws.com/v1/documentation/api/1.37.32/reference/services/s3/bucket/put_object.html


## Correctif de reprise après revue — 16 octobre 2026

Le PNG de secours d'une image transférée vers MinIO reste désormais sur disque
jusqu'à l'acquittement de `finish_image` par PostgreSQL. Une erreur ou un
acquittement perdu conserve donc le PNG et la référence objet pour
réconciliation, sans régénération. Après confirmation SQL, le PNG redondant est
supprimé au mieux ; un échec de nettoyage ne remet pas en cause l'image validée.

La restauration d'un épisode refuse tout journal qui ne respecte pas, pour
chaque asset, l'ordre unique `started → stored → recorded`. Un journal tronqué,
orphelin, dupliqué ou désordonné exige une réconciliation préalable.
