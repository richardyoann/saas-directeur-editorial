# ARCH-MEDIA-01 — validation locale isolée sur Ubuntu 26.04

Date : 18 octobre 2026. Python : 3.14.4 ; Ubuntu 26.04.1 LTS.
Candidat applicatif : `39f2444a0d3c37a572c5c931f60b6a0439c9f0ad` (règles extraites au commit d3fb329). Les commits documentaires ultérieurs doivent être contrôlés sur leur SHA exact et leurs résultats reportés dans la PR #208.

## Résultats et portée

- Régression historique `tests/` et `pilotage/` : **263 tests, 0 échec, 0 erreur, 0 skip**. PostgreSQL 16 isolé, appels modèle simulés ; les tests FFmpeg utilisent des médias synthétiques réels.
- Copie temporaire du main `d08fe0afe62f0ea209da239aeade0bd5f042d30d` avec les changements applicatifs/tests de PR1 : **292 tests, 0 échec, 0 erreur, 0 skip**. L’import de media_storage a été ajusté au contexte récent sans remplacer runtime_secrets. Copie non commitée, non fusionnée ; ce contrôle ne certifie pas un futur merge SHA.
- Studio : **12 parcours réels dans Chrome for Testing 155.0.8059.84, 0 échec, 0 erreur, 0 skip**, sur fixture API simulée. Playwright 1.58.0 ; aucune assertion modifiée. Seul le choix du binaire est adapté par le lanceur ci-dessous.
- `pip check`, compilation Python et `git diff --check` : réussis.
- Aucune régression applicative reproduite après mise en place des prérequis. Les anciens échecs locaux documentés restent historiques ; ils provenaient du Python système incomplet. La première tentative sandbox avec .venv-deployment a été interrompue, non comptée comme succès. L’environnement préexistant n’a pas été modifié.
- CI GitHub : blocage administratif distinct, non résolu par les tests locaux. Aucun test local ne remplace un contrôle requis de branche.

## Environnement reproductible

Aucune dépendance runtime ajoutée au dépôt. Installation autorisée dans `/tmp/arvor-pr1-qa-venv` à partir du requirements.txt existant ; pilote navigateur déclaré par la CI installé séparément. Résolution observée : FastAPI 0.143.0, HTTPX 0.28.1, Pydantic 2.14.0, psycopg 3.3.6, boto3 1.40.0, Starlette 1.8.0. Le manifeste fixe les dépendances directes, pas toutes les transitives ; ce constat n’est pas un audit de vulnérabilités.

```bash
python3 -m venv /tmp/arvor-pr1-qa-venv
/tmp/arvor-pr1-qa-venv/bin/python -m pip install -r requirements.txt
```

PostgreSQL jetable : nom propre à ce passage, port localhost distinct, stockage tmpfs, aucun volume métier ni conteneur existant réutilisé. Vérifier d’abord disponibilité du nom et du port. L’image postgres:16 doit déjà être présente ; `--pull=never` n’installe rien implicitement.

```bash
docker run --detach --rm --pull=never \
  --name arvor-pr1-qa-postgres-20261018 \
  --env POSTGRES_USER=po_test --env POSTGRES_PASSWORD=ephemeral_ci_only \
  --env POSTGRES_DB=po_test --publish 127.0.0.1:55483:5432 \
  --tmpfs /var/lib/postgresql/data postgres:16
```

Les identifiants ci-dessus sont exclusivement synthétiques. Ne pas remplacer la cible par PO_DATABASE_URL ou une base existante. Attendre `pg_isready` avant les tests ; l’autorisation de migration ci-dessous ne vaut que pour cette base jetable.

```bash
PO_TEST_DATABASE_URL=postgresql://po_test:ephemeral_ci_only@127.0.0.1:55483/po_test \
PO_ALLOW_TEST_MIGRATION=yes \
TRACE_TEST_DATABASE_URL=postgresql://po_test:ephemeral_ci_only@127.0.0.1:55483/po_test \
/tmp/arvor-pr1-qa-venv/bin/python scripts/run_regression.py
/tmp/arvor-pr1-qa-venv/bin/python -m pip check
/tmp/arvor-pr1-qa-venv/bin/python -m compileall -q apps editorial pilotage workers workflows scripts
git diff --check
```

Les restrictions sandbox sur les sockets nécessitent des permissions techniques : un test bloqué par le sandbox ne constitue pas un défaut métier. Aucun paramètre de sécurité applicatif n’a été désactivé pour faire réussir les tests.

## Navigateur sans changement système

Playwright 1.58.0 refuse son téléchargement Chromium pour `ubuntu26.04-x64`. Aucun contournement vers Ubuntu 24.04 n’est utilisé. Le Chrome for Testing Linux portable officiel reste exécuté sur Ubuntu 26.04.

- Pilote : `python -m pip install playwright==1.58.0` dans le venv QA uniquement.
- Catalogue officiel : `https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json`.
- Archive utilisée : `https://storage.googleapis.com/chrome-for-testing-public/155.0.8059.84/linux64/chrome-linux64.zip`, extraite dans `/tmp/arvor-pr1-qa-chrome/` ; binaires rendus exécutables.
- Bibliothèques manquantes téléchargées depuis les dépôts Ubuntu 26.04 configurés : libnss3 `2:3.120-1ubuntu2.1` et libnspr4 `2:4.38.2-1ubuntu1`. Extraction `dpkg-deb --extract` dans `/tmp/arvor-pr1-qa-chrome-libs/root`, aucune installation système.

Lanceur temporaire utilisé, sans modification des tests ni de leurs assertions :

```python
import os
import sys
import unittest
from unittest.mock import patch
from playwright.sync_api import BrowserType

sys.path.insert(0, os.getcwd())
os.environ['STUDIO_BROWSER_TESTS'] = 'yes'
original_launch = BrowserType.launch

def portable_launch(self, *args, **kwargs):
    kwargs.pop('channel', None)
    kwargs['executable_path'] = '/tmp/arvor-pr1-qa-chrome/chrome-linux64/chrome'
    return original_launch(self, *args, **kwargs)

suite = unittest.defaultTestLoader.discover('browser_checks', pattern='test_studio_browser.py')
with patch.object(BrowserType, 'launch', portable_launch):
    result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
```

Exécution depuis le checkout concerné :

```bash
LD_LIBRARY_PATH=/tmp/arvor-pr1-qa-chrome-libs/root/usr/lib/x86_64-linux-gnu \
/tmp/arvor-pr1-qa-venv/bin/python /tmp/arvor-pr1-browser-qa.py
```

Le lanceur ne remplace ni client API, ni réponses, ni assertions. Les simulations sont celles de la fixture historique. Ce passage n’est ni une preuve GPU/MinIO réel, ni une recette du PC privé, ni une acceptation éditoriale.

## Nettoyage et reprise

À la fin du passage, arrêter uniquement `arvor-pr1-qa-postgres-20261018` ; son stockage tmpfs est jetable et aucune donnée métier n’y réside. Les outils/bibliothèques QA restent sous /tmp et peuvent être recréés. Ne pas lancer docker compose down, supprimer des volumes ou modifier le conteneur editorial-postgres pour cette validation. La release PC et les checkouts préexistants restent inchangés.
