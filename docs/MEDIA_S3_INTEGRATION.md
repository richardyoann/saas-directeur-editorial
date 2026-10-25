# ARVOR-MEDIA-S3-INTEGRATION

L'adaptateur existant exige désormais HTTPS, une CA PEM absolue lisible via
AWS_CA_BUNDLE et deux fichiers MEDIA_S3_ACCESS_KEY_FILE / MEDIA_S3_SECRET_KEY_FILE.
Les valeurs directes sont refusées. Aucun fallback AWS ou compte administrateur.
TLS vérifie la chaîne et le nom/IP. Endpoint privé à IP littérale ou localhost,
pas d'alias Docker arbitraire. Délais bornés, une tentative, objets conditionnels,
SHA-256 et récupération locale après résultat incertain sont conservés.
Les erreurs publiques restent des codes fixes, sans exception SDK ni chemin privé.
Le compte applicatif doit être provisionné avec IAM sans suppression ; le code ne
peut pas déduire les privilèges effectifs d'une clé. La recette vérifie ce refus.

## WSL

Utiliser les chemins absolus locaux dans .env.example (remplacer your-user),
le bucket existant editorial-artifacts et https://127.0.0.1:9000.
La CA reste externe au dépôt. Aucun certificat ou secret n'est copié dans l'image.
Le backend reste filesystem par défaut ; activer minio exige une livraison validée.

## Docker préparé, non déployé

L'image Python 3.12 contient les dépendances épinglées existantes, ffmpeg,
un utilisateur 1000, un seul worker et une écoute locale. Le profil api ajoute
un filesystem racine en lecture seule, un tmpfs borné, aucune capability et des
montages fichiers strictement en lecture seule. Adapter UID/GID aux fichiers 0600,
sans rendre les secrets lisibles par tous.

Le profil utilise le réseau hôte pour conserver le SAN 127.0.0.1 du certificat.
Compatible Docker Engine Linux sous WSL ; Docker Desktop doit avoir le réseau hôte
activé. Pas de support revendiqué pour un bridge avec un certificat sans SAN DNS.
Le répertoire ARVOR_API_SECRETS_DIR contient uniquement des secrets applicatifs :
editorial_api_token, editorial_web_password, editorial_tenant_id,
editorial_actor_id, po_database_url (rôle PostgreSQL applicatif).
Les chemins S3 et CA sont montés séparément. Aucune importation globale de .env
ni montage des secrets administrateur dans l'API. ARVOR_API_MEDIA_DIR doit exister
et être accessible à l'UID choisi, avec suffisamment d'espace pour les médias.
Les URL locales PostgreSQL/Qwen restent utilisables via le réseau hôte.

Compose conserve les définitions de volumes du main ; il ajoute --certs-dir
/data/.tls à MinIO, dont les certificats existent déjà sur PC. Attention : le
Compose PC possède une configuration Redis TLS/volume distincte de main.
Ne jamais rejouer compose up sur l'ensemble des services depuis ce checkout.
Ne pas utiliser down, -v, volume prune ou recréer un volume.
Après validation du SHA exact seulement, l'opérateur pourra préparer un lancement
ciblé `docker compose --profile api up --no-deps api`, après comparaison du Compose
PC, des noms réels des volumes, des secrets et vérification du port 8000 libre.
Ce document n'autorise pas cette opération.

## Recette

`python -m unittest discover -s tests -p 'test_media*s*.py' -v`

La recette réelle opt-in `python scripts/check_media_s3.py --write-probe` utilise
le backend applicatif, crée un seul objet synthétique, relit et vérifie SHA-256,
puis attend un refus de DeleteObject sur cet objet. Elle ne supprime aucun média
historique ; l'objet est conservé pour nettoyage administrateur séparément autorisé.
Le rapport contient le SHA et la référence de nettoyage, jamais les credentials.
La réussite concerne l'adaptateur réel ; aucune activation de l'API en production
ni validation du parcours HTTP métier n'en découle.

Les versions requirements.txt restent celles de main : boto3 1.40.0 fournit
IfNoneMatch et les options checksum utilisées. La PR dépendances #213 est séparée.
`pip check` confirme la cohérence de l'environnement de test, pas l'absence de CVE.
