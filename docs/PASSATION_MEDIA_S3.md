# Passation — ARVOR-MEDIA-S3-INTEGRATION

Branche indépendante issue de main. Les PR 214/215 restent inchangées.
Configuration PC annoncée par l'utilisateur : HTTPS, compte IAM distinct,
SHA-256 OK, suppression applicative refusée, nettoyage administrateur OK.
Ces preuves historiques ne couvrent pas le nouveau code.

Voir MEDIA_S3_INTEGRATION.md pour configuration, montage CA et recette.
Aucune modification des services en exploitation, volumes, données ou .env PC.
Aucune livraison, fusion, signature d'attestation ou notification Slack.

Implémentation testée réellement : a299050f784c9d418f6e7721ccd9a8d964717520.
Correction de portabilité du test CA : 28aee7d2aedfcc9045ac284be50066985432a112.
Les seules modifications suivantes sont documentaires. Voir MEDIA_S3_EVIDENCE.json.

- Python 3.14 : 287 tests, 0 erreur, 0 échec, 0 skip.
- Python 3.12 : 287 tests, 0 erreur, 0 échec, 0 skip après correction du test CA.
- Recette réelle de l'adaptateur : PUT/GET/SHA-256 et DeleteObject refusé, CA vérifiée.
- Docker : build réussi, smoke UID 1000/racine RO, preflight réel MinIO réussi avec
  fichiers applicatifs/CA seuls montés RO. Aucun serveur de production démarré.
- pip check OK ; pip-audit 2.10.1 : 27 dépendances, 0 vulnérabilité connue.
- Gitleaks 8.28.0 : aucun secret détecté ; syntaxe des trois JS et diff check OK.
- Compose : validation statique OK avec chemins fictifs, sans lancer de services.

OpenCode : première configuration fichier non reconnue, configuration inline reconnue
avec modèle local. Aucun verdict reçu : passerelle 172.31.48.1:8081 en timeout,
loopback 127.0.0.1:8081 refusée. Tentative interrompue, aucun fallback cloud.
Le contrôleur CI signé de la PR 215, non fusionné, n'est pas importé ni qualifié ici.
Ces deux critères restent ouverts ; aucune attestation complète CI OpenCode revendiquée.
Prochaine action : rétablir l'accès au serveur Qwen, puis relancer la revue locale
sur le SHA exact de la PR. Aucun besoin de modifier les PR 214/215.

Un objet synthétique de recette est conservé pour nettoyage administratif autorisé :
bucket editorial-artifacts, clé
bcf14d9c-4b24-466f-9ae4-b83c94a92263/7abc5270-e17f-4edc-a1fe-27c4d2586a1c/voice/efddce96-69a6-4a16-ab40-28c001ece592.wav.
La base jetable arvor-media-s3-test-postgres utilise le port 55484 et tmpfs,
sans volume PC. Elle est arrêtée après les tests, sans suppression de volumes.

La PR draft porte [skip ci] pour éviter les workflows payants à l'ouverture.
Aucune CI GitHub réussie n'en est déduite. La livraison PC attend la validation
humaine du SHA complet final, après résolution des critères ouverts.
