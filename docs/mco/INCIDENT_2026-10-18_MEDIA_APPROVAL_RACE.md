# Concurrence : approbation et finalisation d’image

Date : 18 octobre 2026. Base inspectée : 112475c25fa70e9922c58792f4398ba5842cc89d. Périmètre : tests PostgreSQL jetables et refactoring média PR #208 ; aucun incident de production observé ni accès aux données métier.

## Symptôme et preuve

Le test test_finalization_waits_for_approval_transaction_then_rechecks réserve une image, verrouille le traitement dans une connexion et démarre sa finalisation dans une autre. Avant correction, la finalisation n’attend pas ce verrou : elle lit l’ancien état approuvé et peut conclure alors que la transaction concurrente invalide l’approbation. Le test RED échoue sur l’attente du verrou, après reproduction sur PostgreSQL 16 dédié.

Cause confirmée : lecture du traitement sans verrou dans finish_image, après acquisition du seul verrou asset. Ce test ne prouve pas qu’une course s’est produite sur le PC privé.

## Correction

Dans infrastructure/persistence/media_repository.py, la finalisation verrouille maintenant traitement puis asset. L’ordre est cohérent avec réservation/revue ; l’approbation/scénario courant est revérifié sous verrou avant mutation, audit et outbox dans la transaction existante. Aucun appel réseau ou stockage dans la section verrouillée. Pas de nouvelle migration, verrou distribué ou retry.

## Validation et limites

Le test GREEN observe l’attente PostgreSQL, invalide l’approbation puis vérifie RunConflict après commit de l’invalidation. La régression complète et les tests de double réservation, replay d’une ancienne finalisation et isolation tenant sont exécutés sur une base jetable ; compteurs/SHA finaux dans la PR. Les autres appels finalisation et réservation gardent leurs contrats. Aucun gain chiffré, recette GPU ou acceptation métier déduit.

Le verrou par traitement sérialise brièvement les finalisations de ses scènes ; maintenir la section SQL courte. Une perte d’acquittement garde le fichier de reprise et exige une réconciliation explicite, jamais une régénération automatique. Pour la recette et la reprise, voir docs/ARCHITECTURE_MEDIA.md. Le code n’est pas déployé par cette fiche.
