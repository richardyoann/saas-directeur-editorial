# Incident CI — intégration Arvor, 21 octobre 2026

## Symptôme et preuve

Toutes les exécutions GitHub Actions du dépôt échouent **avant le démarrage
d'un runner**. Runs du 21/10/2026 sur `main` (`d08fe0af`) :
`CI annotation incident watch` (#39603098181), `Secret exposure scan`,
`CI supply-chain guardrails`, `Dependency security audit`,
`Automated CI triage and release evidence` → `failure`, avec
`steps: 0` et `runner_name` vide sur tous les jobs.

Annotation du check-run 117377766071 (API
`check-runs/117377766071/annotations`) :

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans'
> section in your settings

Le symptôme touche `main` lui-même, pas seulement les branches de PR : aucun
défaut applicatif n'est établi par cet échec de démarrage. Cause administrative
précise non établie (paiements échoués **ou** plafond de dépenses à augmenter,
les deux alternatives données par GitHub).

## Hypothèse et correction

Cause immédiate confirmée : restriction de facturation/quota au niveau du
compte de facturation GitHub. Correction hors périmètre du dépôt : action
d'administrateur de compte sur `Billing & plans`. Diagnostic CodeQL/CI
documenté dans la PR #210, qui reste bloquée pour la même raison.

Aucun contournement appliqué : pas de repointage de la CI sur le runner
self-hosted `editorial-pc` (ce runner héberge le PC privé et ne doit jamais
exécuter du code de PR), pas de désactivation de workflow, pas de contournement
de protection de branche, pas de `--admin` sur une fusion.

## Intégration préparée (PR de suivi #214)

Huit PR Arvor ont été intégrées dans l'ordre de dépendance
**#197 → #198 → #202 → #203 → #208 → #209 → #200 → #211** sur la branche
`ops/INTEG-20261021-arvor-sync`. Le `merge-base` de cette branche avec
`origin/main` est exactement `d08fe0af` : aucun contenu étranger n'est
introduit. Conflits résolus dans `apps/web/studio.html` (durée verrouillée à
75 s en lecture seule, scènes libres 1..6 avec 5 par défaut),
`apps/web/arvor_next.js` (options par champ, création à 75 s / 5 scènes),
`browser_checks/test_studio_browser.py` (helper `create()` réconcilié +
assertions de non-régression) et `docs/mco/README.md`.

## Validation et limites

Contrôles locaux exécutés sur le SHA de code `910979b`, reproduction des sept
portes GitHub Actions (matrice Python 3.12 et 3.14, PostgreSQL 16 jetable
dédié `127.0.0.1:55483`, `node --check`, parcours Chromium réels, `pip-audit`
2.10.1, `gitleaks` 8.28.0 différentiel, garde-fous supply-chain, recette
vidéo 75 s synthétique) :

| Porte | Résultat |
| --- | --- |
| régression Python 3.12 | 390 tests, 0 échec, 0 erreur, 0 skip |
| régression Python 3.14 | 390 tests, 0 échec, 0 erreur, 0 skip |
| parcours navigateur Chromium | 18 parcours réussis |
| `node --check` | PASS |
| `pip-audit` | aucune vulnérabilité connue |
| `gitleaks` différentiel | 0 nouvelle finding (2 historiques inherited) |
| `ci_policy` / `ci_autonomy` / `ci_status_report` | PASS |
| recette vidéo 75 s synthétique | `verified: true` (ffprobe, 720x1280, 75 s) |

La base de données métier n'a pas été touchée ; le conteneur PostgreSQL de
recette est jetable et dédié. Aucun skip n'est présenté comme une réussite.

**Aucune fusion vers `main` n'a été réalisée** : les PR #209 et #208 imposent
une CI GitHub verte sur le SHA exact et refusent explicitement que les preuves
locales contournent le blocage de facturation. La condition de fusion n'est
donc pas remplie, et l'autorisation permanente de fusion — qui vaut *après
contrôles requis réussis* — ne s'applique pas. La PR #214 est laissée en
brouillon.

**Aucune mise en production**, aucune activation de release, aucun changement
de `LOCAL_PC_ENABLED` ou `LOCAL_PC_APPROVED_SHA` (SHA épinglé inchangé à
`1aeddcb8…`) : la branche d'intégration ne peut pas déclencher
`local-delivery.yml` (SHA différent de l'épinglé **et** conclusion de
régression non `success`).

Limites : les portes locales reproduisent les workflows GitHub mais ne valent
pas exécution sur runner hébergé — le journal GitHub du SHA reste manquant.
Recette Qwen réelle non exécutée (serveur de modèle local indisponible dans
cet environnement). Pas de recette PC, pas de validation artistique, pas de
test GPU/Vulkan réel. La validation éditoriale (acceptation métier du
contenu) reste obligatoire et n'est pas acquise.

## Levée du blocage

1. Corriger la facturation ou le plafond de dépenses du compte GitHub.
2. Relancer la CI sur le SHA de tête de la branche d'intégration : les sept
   portes doivent passer sur ce SHA exact.
3. Fusionner alors #214, ou les huit PR dans l'ordre indiqué si la fusion
   individuelle est exigée (les conflits y sont déjà résolus).
4. Aucun déploiement PC sans accord explicite sur le SHA complet exact.

La fusion vers `main` déclenche une CI et, si `LOCAL_PC_ENABLED=true`, une
livraison involontaire : vérifier `LOCAL_PC_APPROVED_SHA` avant chaque fusion.
