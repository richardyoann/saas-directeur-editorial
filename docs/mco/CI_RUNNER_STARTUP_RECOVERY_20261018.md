# Arvor — CI bloquée avant le démarrage des runners (18/10/2026)

## État constaté et certitude

Le **18 octobre 2026**, plusieurs workflows GitHub-hosted indépendants échouent
en 3 à 6 secondes, avant une seule étape (jobs `steps: null` ou `[]`,
`runner_id` non attribué, logs `404 BlobNotFound`). Un tel résultat **ne
constitue pas l'échec des tests applicatifs** ; il ne démontre pas non plus la
cause exacte. Les hypothèses à examiner : allocation du runner GitHub,
facturation/quota/limite de dépense du dépôt privé, habilitations Actions,
restriction de compte, dégradation GitHub.

Exemples vérifiés :
- Régression Python PR #209 :
  https://github.com/richardyoann/saas-directeur-editorial/actions/runs/39127783667
  Jobs Python 3.12 `117676447110`, Python 3.14 `117676447429`
  — failure, `steps: null`.
- Audit dépendances PR #209 :
  https://github.com/richardyoann/saas-directeur-editorial/actions/runs/39127783447
  Job initial `117676445810`. Une seule relance ciblée effectuée
  le 18/10/2026 : **tentative 2 = failure**, job `117695273992`,
  toujours sans étapes/logs.
- Navigateur PR #209 :
  https://github.com/richardyoann/saas-directeur-editorial/actions/runs/39127783463
  Job `117676445597`, mêmes symptômes.

La lecture de `/actions/permissions`, `/actions/billing/usage` et
`/actions/runners` est **non accessible via le connecteur GitHub actuel** ;
aucune valeur de quota, facturation ou configuration du compte ne peut être
affirmée.

## Procédure de résolution — action propriétaire GitHub

1. Dans la page de **l'audit dépendances** ci-dessus, regarder l'en-tête de
   la tentative 2 et les annotations du job. Consigner tout message
   `startup_failure`, runner unavailable, account restriction ou billing.
2. GitHub : **avatar → Settings → Billing & Licensing → Usage**.
   Vérifier le produit Actions : minutes incluses/restantes, budgets et limites
   de dépense, moyens de paiement, alertes/contrôle d'accès. Ne pas
   augmenter de budget sans accord explicite.
3. Dépôt privé : **Settings → Actions → General**. Vérifier Actions activé,
   stratégie autorisant les actions déjà épinglées par SHA et disponibilité des
   runners GitHub-hosted. Ne pas élargir arbitrairement les permissions
   `GITHUB_TOKEN` : le dépôt définit les droits minimaux par workflow.
4. Consulter https://www.githubstatus.com/ pour les incidents Actions,
   y compris les incidents régionaux ou liés aux journaux. L'incident
   GitHub du 13 octobre ne prouve pas que l'incident du 18 a la même cause.
5. Après correction des réglages ou confirmation de la disponibilité,
   **relancer un seul job non sensible** sur une PR (audit dépendances),
   attendre les étapes `Set up job` et les logs. Si cela échoue encore sans
   étape, **ne pas multiplier les relances** : ouvrir un ticket
   https://support.github.com/contact en indiquant les URL/IDs, les horaires,
   les étiquettes `ubuntu-24.04`, l'absence de steps et le BlobNotFound.
6. Seulement quand un runner commence à exécuter, lancer la régression
   complète sur Python 3.12/3.14, audit dépendances, scan de secrets,
   guardrails et parcours Chromium ; **zéro skip**. Les résultats des PR
   antérieures ne prouvent pas l'état du nouveau SHA.

## Correctif de supervision proposé

`scripts/ci_status_report.py` classe les échecs sans étape et sans runner
sous `runner_startup_unverified` : ne plus recommander de corriger
`pip_audit` ou les tests de Python quand ils n'ont jamais démarré.
La catégorisation est conservatrice ; aucun message de job n'est traité
comme une instruction ni publié.

### Revue et correction du format API — 18 octobre 2026

La réponse REST brute du run `39127985728` (jobs `117677042003` et
`117677042238`) indique `steps: []`, `runner_id: 0`, `runner_name: ""`.
Le premier correctif ne reconnaissait que `runner_id: null` et manquait
donc ce cas réel. Le diagnostic accepte maintenant explicitement `null`
ou l'entier `0`, avec étapes explicitement vides et aucun nom de runner.
Un champ `runner_id` absent reste une preuve insuffisante ; un runner
positif ou nommé interdit cette classification. Les booléens ne sont pas
assimilés à l'entier zéro. L'indication concerne les jobs en échec/timeout,
sans affirmer que tous les autres jobs du workflow sont restés sans runner.

Test de non-régression ajouté avant correction : 13 tests ciblés exécutés,
1 échec sur le cas réel `runner_id: 0` ; après correction et séparation du
cas de non-régression : 14 tests réussis, 0 échec, 0 erreur, 0 skip sous
Python 3.12.14. Environnement de revue isolé des identifiants (variables vidées),
appels réseau bloqués et API simulée : ce contrôle n'est ni une CI GitHub
complète ni une validation du PC ou de PostgreSQL.

Ce correctif améliore la **qualité du diagnostic**, **pas l'accès aux
runners hébergés par GitHub**. Une PR non fusionnée ne le rend pas actif.

## Alternative si le service hébergé reste bloqué

L'instance PC possède un runner privé `editorial-pc`, réservé à la livraison.
**Ne jamais réaffecter ce runner de production aux PR non fiables** :
les codes exécutés auraient accès à la machine et potentiellement aux
ressources privées. Une CI alternative auto-hébergée exigerait une **nouvelle
infrastructure isolée**, comptes/volumes/secrets distincts, aucun accès
au runtime Arvor, runner éphémère, revue des privilèges Docker, et accord
explicite avant installation ou activation. Aucune modification de
runners ou de variables de livraison n'est effectuée par cette PR.

## Interdictions de contournement

- Ne pas fusionner des PR en échec, modifier les statuts à la main ou retirer
  les gates obligatoires.
- Ne pas activer `LOCAL_PC_ENABLED` ni déployer un SHA non approuvé.
- Ne pas rendre public le dépôt pour récupérer des minutes CI.
- Ne pas effacer PostgreSQL/MinIO ni installer des paquets sur le PC pour
  corriger un job GitHub-hosted qui n'a même pas démarré.

Références : issue #205 ; docs GitHub Actions et facturation.
