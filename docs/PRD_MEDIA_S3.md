# PRD — stockage média sécurisé

Objectif : conserver les nouveaux médias privés dans MinIO existant, sans migration
ni suppression de l'historique local. L'activation reste opt-in après validation
humaine du SHA complet. Les sources locales incertaines sont conservées.

Critères : HTTPS avec CA et nom vérifiés, identité IAM applicative par fichiers,
aucun identifiant administrateur dans l'API, intégrité SHA-256 à la lecture,
écriture conditionnelle sans retry ambigu, suppression IAM interdite, isolation
par tenant/run/asset, erreurs expurgées, configurations WSL et Docker documentées.

Préparé : adaptateur renforcé, tests de sécurité et recette réelle opt-in, image
non privilégiée, profil API. Hors livraison : migration des médias existants,
création de bucket/policy, modification des volumes et déploiement PC.
Les résultats effectifs et limites sont consignés dans PASSATION_MEDIA_S3.md.
