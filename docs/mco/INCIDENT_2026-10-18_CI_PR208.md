# Incident CI — PR #208, 18 octobre 2026

## Symptôme et preuve

Sur le SHA d3fb3294352e1ce2ddfb99ce5de147d10c08d5a1, le run Full regression #39124843757 est failure. Les jobs Python 3.14 (#117667676445) et 3.12 (#117667676680) ne contiennent aucune étape exécutée. Les quatre autres contrôles PR apparaissent également failure ; leur cause individuelle n’est pas encore confirmée.

Annotation du job 3.14 lue via l’API GitHub check-runs/117667676445/annotations : GitHub signale que le job n’a pas démarré en raison de paiements récents échoués ou d’une limite de dépenses à augmenter. L’annotation ne distingue pas ces deux causes administratives. Aucun défaut applicatif n’est établi par cet échec de démarrage.

## Hypothèse et correction

Cause immédiate confirmée pour ce job : restriction de facturation/quota empêchant son démarrage. Cause administrative précise non établie. Aucun correctif code, changement de workflow, runner, facturation ou accès effectué. Pas de relance manuelle répétée. L’administrateur du compte doit examiner Billing & plans ; cette opération sort du périmètre du refactoring.

## Validation et limites

Après résolution administrative, relancer les contrôles sur le SHA final exact de la PR, vérifier que les étapes démarrent puis exiger la régression complète sans skip, PostgreSQL dédié compris. Les tests locaux purs ne remplacent pas cette validation. Aucun résultat éditorial ni release PC accepté. Aucun déploiement autorisé par un rapport CI.

Le checkout local initial précède le main distant d08fe0afe62f0ea209da239aeade0bd5f042d30d ; GitHub indique PR fusionnable au contrôle. Aucune fusion réalisée. Les changements distants de secrets dans media_storage sont à préserver et l’intégration avec main reste à tester par la CI de PR.

## Environnement QA local rétabli — problème distinct

Symptôme local : dépendances absentes dans Python système, et téléchargement Chromium Playwright refusé sur Ubuntu 26.04. Correction autorisée : venv isolé sous /tmp, requirements existant, PostgreSQL tmpfs dédié ; navigateur Chrome for Testing portable et bibliothèques Ubuntu 26.04 extraites sous /tmp. Aucun paquet système, volume métier ou règle de production modifié. Validation : 263 tests et 12 parcours navigateur réussis sans skip sur le candidat 39f2444 ; combinaison temporaire avec main d08fe0a : 292 tests réussis. Voir ../plans/ARCH_MEDIA_01_LOCAL_QA.md. Le problème administratif GitHub demeure ouvert et n’est pas présenté comme corrigé.
