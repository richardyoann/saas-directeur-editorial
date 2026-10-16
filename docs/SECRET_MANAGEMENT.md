# Arvor — gestion externe des secrets

## Configuration
Les identifiants PostgreSQL et MinIO ne figurent plus en clair dans compose.yml.
Avant toute création de conteneur, renseigner des chemins hôtes ABSOLUS hors dépôt
dans ARVOR_POSTGRES_PASSWORD_FILE, ARVOR_MINIO_ROOT_USER_FILE et
ARVOR_MINIO_ROOT_PASSWORD_FILE. Utiliser des fichiers 0600 dans un dossier 0700.
Ces fichiers sont montés par Compose dans /run/secrets/ et sont lus via les
variables POSTGRES_PASSWORD_FILE, MINIO_ROOT_USER_FILE et MINIO_ROOT_PASSWORD_FILE.
Les valeurs ne doivent jamais être copiées dans Git, les logs ou un chat.

Le runtime API / worker accepte soit NAME (variable), soit NAME_FILE (chemin
absolu) pour EDITORIAL_API_TOKEN, EDITORIAL_WEB_PASSWORD, PO_DATABASE_URL,
EDITORIAL_TENANT_ID, EDITORIAL_ACTOR_ID, MEDIA_S3_ACCESS_KEY,
MEDIA_S3_SECRET_KEY et EDITORIAL_GITHUB_READ_TOKEN. Ne jamais définir les
deux sources simultanément. La lecture depuis CREDENTIALS_DIRECTORY/NAME
permet systemd LoadCredential et LoadCredentialEncrypted, ou un agent Vault.
Aucun gestionnaire de coffre n'est installé ni configuré automatiquement.

## Protection des volumes existants
IMPORTANT : ne pas lancer docker compose up -d sur le PC immédiatement.
POSTGRES_PASSWORD_FILE ne change PAS le mot de passe du rôle présent dans
une base initialisée. Modifier uniquement un fichier peut briser la connexion.
Procédure : sauvegarder PostgreSQL et MinIO, restaurer sur clone isolé,
vérifier identifiants actuels hors logs, planifier rotation de rôle DB et
MinIO avec adaptation client, tester et documenter le rollback, puis demander
l'autorisation explicite du SHA de livraison PC. Ne jamais exécuter down -v.

## Contrôles et limites
python3 -m unittest tests.test_runtime_secrets -v
python3 scripts/ci_policy.py
Régression CI Python 3.12 et 3.14, scan dépendances, tests navigateur.
Vérifier le comportement avec secrets injectés sur le PC avant toute MEP.
La présence de secrets anciens dans l'historique Git, les sauvegardes
ou les logs n'est PAS exclue par ce changement : scan et rotation dédiés.
Le SaaS public reste bloqué tant que comptes, RBAC, RLS et pentest
n'ont pas été traités. Les identifiants du test PostgreSQL CI sont
synthétiques et ne constituent pas des comptes d'exploitation.
