# INC-2026-10-17 — GitHub Actions échoue avant affectation du runner

- Ouverture : 17 octobre 2026, 09:40–09:55 Europe/Paris (fenêtre observée via GitHub).
- Contexte : dépôt privé `richardyoann/saas-directeur-editorial`, PR #196, branche `design/arvor-studio-v2-20261017`.
- Gravité : **P1 pour la chaîne CI/validation**, pas une panne applicative PC démontrée.
- Données métier / Postgres / MinIO : **aucune intervention**.
- Impact : régression, navigateur, audits, scan de secrets et revue de risques ne démarrent pas. Livraison et fusion bloquées conformément aux garde-fous.

## Preuves observées

1. CI précédente pour la PR #108 (workflow `Full regression` run `38980442075`, 16/10/2026 23:15 UTC) : succès, **14 étapes** exécutées sur les jobs Python 3.12 et 3.14.
2. PR #196, SHA initial `96b6e0b4ac3977c5f5c0f449fdfe240e95b08e9a` : `Full regression` run `39014500123`, jobs 3.12 et 3.14 `failure` en ~2 secondes, **aucune étape**, `runner_id=0`.
3. PR #196 après ajouts de tests : run `39015233685`, jobs 3.12 et 3.14 `failure` en ~3 secondes, **aucune étape**, `runner_id=0`.
4. Même période : les jobs sur `main` des workflows `CI annotation incident watch` et `Automated CI triage and release evidence` échouent également. Ce défaut traverse des branches et workflows différents.
5. Les journaux de jobs renvoient une erreur de récupération `BlobNotFound`; les annotations de contrôle ne sont pas accessibles par le connecteur dans cette session.

## Diagnostic

**Confirmé :** échec *avant démarrage du runner*, non démontré comme échec de tests Python, JS, navigateur ou secrets.
**Cause racine : non confirmée.** Hypothèses à vérifier dans les paramètres GitHub avec accès administrateur : facturation ou limites d'utilisation GitHub Actions, indisponibilité / blocage des runners hébergés, configuration Actions/politique du dépôt ou incident GitHub. La présence de plusieurs workflows d'alerte `workflow_run` entraîne une multiplication des échecs à observer ; elle n'établit pas la cause initiale.

## Procédure de rétablissement non destructive

1. GitHub → dépôt → **Actions** → `Full regression` → ouvrir le dernier job en échec → lire le *message d'annotation* affiché en en-tête. Conserver le texte exact, sans token ni donnée personnelle.
2. GitHub → compte/organisation → **Settings → Billing and licensing** : vérifier disponibilité/quota/budget Actions et éventuel blocage de paiement.
3. GitHub → dépôt → **Settings → Actions → General** : vérifier si l'exécution des Actions et le choix de runners sont autorisés, sans modifier les politiques pour masquer l'échec.
4. Consulter `https://www.githubstatus.com/` pour un incident GitHub Actions au moment concerné.
5. Quand la cause est résolue, **relancer seulement** les jobs requis de la PR #196 puis lire `steps` et logs complets. Le résultat d'une relance n'est pas une preuve tant qu'une exécution réelle n'a pas eu lieu.
6. Valider `node --check apps/web/arvor_next.js`, `python scripts/run_regression.py`, `STUDIO_BROWSER_TESTS=yes python -m unittest discover -s browser_checks -p test_studio_browser.py -v` dans un environnement d'intégration *jetable*, puis audits de sécurité. Ne pas utiliser la base de l'utilisateur pour une suite de tests.
7. Ne fusionner qu'après CI complète réellement verte, revue du diff, recette navigateur/desktop/mobile et accord explicite. La **livraison PC** constitue une opération distincte nécessitant le **SHA complet approuvé**.

## Corrections faites en parallèle dans la PR #196

- Migration des assertions UX V2 vers une classe `unittest.TestCase`, afin qu'elles soient effectivement découvertes par `scripts/run_regression.py`.
- Ajout de tests navigateur sur filtres vides, journal → historique IA authentifié, et menu mobile 390 px.
- **Aucune modification** au runner PC, secrets, configuration de livraison, version `/studio` actuelle ou données métier.

## Critère de fermeture

Preuve documentée d'un **runner réellement affecté**, étapes exécutées, toutes suites obligatoires vertes sans bypass et recette V2 réalisée. Sinon, incident ouvert.
