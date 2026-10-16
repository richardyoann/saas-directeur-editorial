# OPS-CI-WARN — Incidents et maintenance CI/CD

Correction proposée le 17/10/2026, à qualifier en PR avant intégration.
Aucune modification de la base métier, du service PC ou du runner local.

## Pourquoi les warnings sont passés

Le script de triage historique classe les runs GitHub Actions par conclusion
success/failure mais ne lit pas leurs annotations. La sortie Node.js 20 ou
la migration ubuntu-latest pouvaient donc passer inaperçues même sur une CI verte.
pip-audit audite les dépendances Python, pas les actions GitHub.

## Correction

1. CI supply-chain guardrails : sur PR, main et chaque matin, impose SHA
   immuables pour les actions, bloque les anciens SHA Node20 approuvés,
   interdit ubuntu-latest non maîtrisé, signale permissions dangereuses
   et vérifie la présence de Dependabot.
2. CI annotation incident watch : déclenché à la fin des principaux workflows
   et chaque matin en rattrapage (36 h dans les 100 derniers runs).
   Il consulte les annotations GitHub Checks y compris sur un run success,
   crée une Issue unique par ID de run lorsque warning/failure apparaît
   ou notice de dépréciation/Ubuntu pertinente, et déduplique les relances.
   L'Issue ne contient que catégorie prédéfinie, SHA et lien vers le run ;
   jamais le texte brut d'annotation, les prompts, les logs ni les tokens.
   Une panne API fait échouer le watcher plutôt que de déclarer un succès.
3. Dependabot propose des PR hebdomadaires GitHub Actions, Python et Docker ;
   ces PR ne sont jamais fusionnées ni livrées automatiquement.
4. Tous les jobs GitHub-hosted passent à ubuntu-24.04 stable jusqu'à une
   campagne de qualification Ubuntu 26.04. Cela ne change PAS le runner
   privé WSL Ubuntu 26.04, documenté comme v2.338.0 le 12 octobre.
   Vérifier sa version active avant toute MEP ; les actions Node24 ont besoin
   d'un runner compatible.

## Notifications et limites

Les alertes apparaissent dans GitHub Issues et Actions. Leur arrivée dans
les emails ou notifications mobiles dépend des réglages GitHub et de
l'abonnement aux Issues : la création d'une Issue ne garantit pas un email.
Le moniteur n'analyse ni les logs ni les dépendances natives/FFmpeg ni tout
l'historique Git pour d'éventuels secrets. Il ne qualifie pas de CVE chaque
warning. Ne pas l'utiliser comme preuve d'une revue sécurité exhaustive.

L'exécution workflow_run avec issues:write checkout uniquement main de
confiance, sans exécuter le code non fiable des PR. Aucune issue n'est créée
par simple lecture d'un log arbitraire, et aucun secret de prod n'est requis.

## Vérifier

~~~bash
python3 -m unittest tests.test_ci_policy tests.test_ci_annotation_watch -v
python3 scripts/ci_policy.py
python3 scripts/run_regression.py
~~~

Après merge, tester le véritable workflow CI annotation incident watch et
ses autorisations. Sur branche isolée, un step peut générer ::warning::
tout en réussissant ; vérifier la nouvelle Issue, la déduplication après
rerun et l'absence de données brutes. Vérifier séparément la notification
GitHub souhaitée. Corriger en PR puis revenir à un run sans warnings.
Pour revenir en arrière, désactiver les deux nouveaux workflows ou
revert cette PR ; ne pas toucher aux volumes PC. Une fusion ne vaut jamais
approbation de livraison PC (SHA exact requis).
