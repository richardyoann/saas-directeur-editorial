# Passation — MLflow privé Arvor

Date : 27 octobre 2026. Branche `feat/mlflow-integration-20261027`, base
`origin/main` `079317cd912168ec58ce4df377c49441cfc40186`.

## État livré localement

- Service utilisateur `arvor-mlflow.service` : actif, `enabled`, redémarrage
  automatique, durci, un seul worker, loopback `127.0.0.1:5000`.
- PostgreSQL dédié `mlflow` / `mlflow_app` ; accès à la base métier refusé.
- MinIO dédié `mlflow-artifacts` ; accès au bucket métier refusé.
- Authentification basique active ; `/health` sans identifiants renvoie 401.
- Tracker `infrastructure/observability/mlflow_tracker.py` : désactivé par
  défaut, fail-open, file/spool bornés, rejeu idempotent.
- Instrumentation Qwen, image sd.cpp, voix Piper, piste WAV existante et export
  FFmpeg.
- Recette réelle 15/15 sur le poste WSL ; rapport JSON hors dépôt.
- Documentation d'exploitation : `docs/MLFLOW.md`.

## Ce qui n'a pas été fait

- Aucun push, aucune PR, aucune fusion.
- Aucun déploiement PC, aucune modification de `~/editorial-runtime/current`.
- Aucune migration métier, aucun changement de base, bucket, volume ou secret
  métier.
- Aucune activation MLflow dans le service API actuellement déployé.
- Aucun abonnement ou service payant.

## Reprise opérateur

1. Vérifier `systemctl --user is-active arvor-mlflow.service` et le healthcheck
   avec `scripts/mlflow_healthcheck.py`.
2. En cas de spool non vide, exécuter `--replay` une fois et vérifier
   `replayed/failed` ; ne jamais supprimer le spool à la main sans diagnostic.
3. Pour activer un client Arvor, fournir `client.env` (0600) au processus et
   positionner `ARVOR_MLFLOW_ENABLED=true` ; sans cette variable, aucun envoi.
4. Avant toute livraison PC, obtenir l'accord explicite sur le SHA complet et
   suivre `docs/mco/RUNBOOK_DIAGNOSTIC_PC.md`.

## Limites à traiter ensuite

- Embarquer Piper dans l'image si la voix doit être disponible en production.
- Décider d'une politique de rétention (le spool et les runs ne sont pas purgés
  automatiquement).
- Ajouter un contrôle navigateur lorsque Chromium/Playwright sera installé.
- Mesurer la mémoire MLflow sous charge réelle et ajuster le worker unique.

## Preuves

Le reçu de recette contient le SHA, les identifiants de runs, les empreintes et
les durées. Il est conservé hors dépôt et ne doit pas être publié avec des
secrets. Les commandes sont dans `docs/MLFLOW.md` §6 et §7.
