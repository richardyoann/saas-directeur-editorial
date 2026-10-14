# RUNBOOK MCO — Diagnostic et remise en service du SaaS sur PC privé

**Portée :** atelier privé Arvor Studio / Directeur éditorial : Windows + Qwen/llama.cpp Vulkan, WSL Ubuntu 26.04, FastAPI port 8000, PostgreSQL Docker port 5432, GitHub Actions runner `editorial-pc`.

**Principe :** diagnostiquer en **lecture seule**, qualifier la cause, protéger les données, corriger **un seul composant à la fois**, puis vérifier le service réel. Ce guide ne constitue pas une autorisation automatique de MEP. La validation du **SHA exact** reste obligatoire.

## 0. Sécurité, conventions et chemins

| Contexte | Prompt typique | Commandes |
| --- | --- | --- |
| **Windows PowerShell** | `PS C:\...>` | `Get-NetTCPConnection`, `Test-Path`, `Get-Process`, invocation `llama-server.exe`. |
| **Ubuntu WSL (Bash)** | `yoann_admin@...:~$` | `git`, `systemctl --user`, `docker`, `curl`, `python`, `ss`, `ip route`. |
| **PowerShell → WSL** | `PS C:\...>` | `wsl -d Ubuntu-26.04 -e <commande Linux> ...` ; utiliser Bash seulement pour les opérateurs shell. |

Chemins **observés pendant l'incident** (vérifier qu'ils existent ; ne jamais déduire un chemin depuis un ancien document) :

```text
/home/yoann_admin/saas-directeur-editorial         # copie de travail SANS .git
/home/yoann_admin/saas-directeur-editorial-github  # dépôt AVEC .git
/home/yoann_admin/editorial-runtime/current        # lien symbolique -> releases/<SHA>-<timestamp>
/home/yoann_admin/editorial-runtime/private/runtime.env  # secrets persistants
/home/yoann_admin/editorial-runtime/last_delivery.json
/home/yoann_admin/editorial-runtime/backups
```

Ne jamais partager `runtime.env`, les URL PostgreSQL complètes, les cookies, le bearer token, `POSTGRES_PASSWORD`, les prompts et réponses brutes, ni `docker inspect` intégral. Préférer des noms d'état et des codes HTTP. **Avant tout essai : ne pas supprimer les volumes ou les releases.**

## 1. Arbre de décision express (< 5 minutes)

```text
Interface Studio inaccessible
  ├─ /health inaccessible (curl: 7, timeout) ?
  │    └─ Vérifier systemctl --user status, journalctl, port 8000
  ├─ /health = 200 ET /studio = 404 ?
  │    └─ Vérifier SHA current, reçu, source GitHub -> ancienne release probable
  ├─ /studio = 200 mais connexion refusée (401/429/503) ?
  │    └─ Vérifier présence/longueur du mot de passe, session, rate limit, Origin/CSRF
  ├─ /ready = 503 ?
  │    ├─ PostgreSQL : conteneur, pg_isready, TCP, SELECT 1
  │    ├─ Qwen : port 8081 Windows, /v1/models, /health depuis WSL
  │    └─ Si mode async true : worker enregistré/supervisé
  └─ Studio = 200, ready = 200, génération en erreur ?
       └─ Rechercher code d'erreur et UUID, vérifier finish_reason,
          schéma IA, audit et snapshots ; JAMAIS de rejeu automatique incertain
```

`/health` = vie de FastAPI seulement ; `/ready` = dépendances (DB + LLM ; **et worker si async activé** depuis le correctif JOB-001). Un `404` sur `/ready` suggère une ancienne release, **pas** « Qwen KO ».

### Collecte initiale sans secrets (Bash WSL)

```bash
date -Is
cd /home/yoann_admin/saas-directeur-editorial-github
git status --short
git rev-parse origin/main
git rev-parse HEAD

systemctl --user is-active editorial-api.service
systemctl --user is-active editorial-actions-runner.service
systemctl --user status editorial-api.service --no-pager -l
journalctl --user -u editorial-api.service -n 35 --no-pager -o cat

readlink -f ~/editorial-runtime/current
ls -ld ~/editorial-runtime/current ~/editorial-runtime/current/.env
# last_delivery.json contient le SHA et des états, pas un secret.
cat ~/editorial-runtime/last_delivery.json

for route in health ready studio; do
  curl -sS --max-time 5 -o /dev/null -w "$route : HTTP %{http_code}\n" \
    "http://127.0.0.1:8000/$route"
done
```

Les journaux peuvent exceptionnellement contenir des données sensibles : **relire avant de transmettre**. La commande `git status --short` dans le bon checkout ne modifie rien.

### Diagnostic consolidé de release (Bash WSL, si script disponible)

```bash
cd /home/yoann_admin/saas-directeur-editorial-github
# Utiliser le SHA APPROUVÉ en entier, pas un hash raccourci.
.venv/bin/python scripts/diagnose_runtime.py \
  --root /home/yoann_admin/editorial-runtime \
  --expected-sha <SHA_COMPLET_APPROUVE>
```

Si le checkout n'a pas de venv, appeler l'interpréteur connu de la release `~/editorial-runtime/current/.venv/bin/python` avec le **même script**. Aucun `git init`, `git reset --hard` ou déplacement de `.git`.

## 2. FastAPI / systemd

**Symptômes :** port 8000 refusé, service `inactive (dead)` ou `failed`, navigateur ne charge pas Studio.

```bash
systemctl --user show editorial-api.service -p ActiveState -p SubState -p WorkingDirectory -p MainPID -p UnitFileState
systemctl --user status editorial-api.service --no-pager -l
journalctl --user -u editorial-api.service -n 50 --no-pager -o cat
ss -lnt | grep ':8000' || true
```

**Correction conditionnelle, seulement après avoir lu les logs et confirmé qu'aucune autre API active n'occupe le port :**

```bash
systemctl --user start editorial-api.service
sleep 5
systemctl --user is-active editorial-api.service
curl -sS -i --max-time 5 http://127.0.0.1:8000/health
```

Résultat attendu `active` + `HTTP 200`. Lors de l'incident le premier appel a échoué **moins d'une seconde après** le démarrage : attendre `Application startup complete` avant de conclure. `disabled` concerne l'activation au login/boot, pas nécessairement l'état présent ; n'activer le démarrage automatique qu'après décision d'exploitation.

## 3. Mauvais dépôt, mauvaise release et HTTP 404

**Symptômes :** `fatal: not a git repository`, ou `/health=200` alors que `/studio=404`, `/ready=404`.

```bash
find /home -maxdepth 5 -name .git -print
git -C ~/saas-directeur-editorial-github fetch origin
git -C ~/saas-directeur-editorial-github rev-parse origin/main
readlink ~/editorial-runtime/current
realpath -e ~/editorial-runtime/current
ls -ld ~/editorial-runtime/releases/*/
```

Comparer trois preuves : SHA `origin/main`, répertoire pointé par `current`, reçu `last_delivery.json` ; le reçu doit en outre indiquer `installed_live=passed`. Aucun SHA d'un run GitHub ancien ne suffit à prouver une livraison. Ne pas changer le lien symbolique manuellement : le script `scripts/deploy_local.py` gère candidate, contrôle et rollback.

## 4. PostgreSQL Docker et authentification

**Symptômes :** `psycopg.OperationalError` / `ConnectionRefusedError`, erreurs sur `/ready`, `pg_isready` rejette pendant le boot.

```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker inspect editorial-postgres --format '{{.State.Status}} exit={{.State.ExitCode}} error={{.State.Error}}'
docker inspect editorial-postgres --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{println}}{{end}}'
docker logs --tail 35 editorial-postgres
ss -lnt | grep ':5432' || true
```

Le volume observé est `saas-directeur-editorial_postgres_data`. **Ne jamais appliquer `docker compose down -v`, `docker volume prune`, `docker rm`, `initdb` ou une migration comme correctif exploratoire.**

Si `editorial-postgres` est `Exited`, que le volume est présent et qu'aucune autre instance ne l'utilise, un opérateur peut le redémarrer (action de correction, **non** lecture seule) :

```bash
docker start editorial-postgres
for i in $(seq 1 15); do
  docker exec editorial-postgres pg_isready -U editorial -d editorial && break
  sleep 2
done
docker logs --tail 20 editorial-postgres
```

Il est possible de lire `rejecting connections` pendant la reprise WAL, puis `database system is ready to accept connections`. Pour vérifier les identifiants **applicatifs** sans jamais les afficher :

```bash
~/editorial-runtime/current/.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
import psycopg
config = dotenv_values(Path.home() / "editorial-runtime/private/runtime.env")
try:
    with psycopg.connect(config["PO_DATABASE_URL"], connect_timeout=5) as db:
        ok = db.execute("SELECT 1").fetchone() == (1,)
    print("POSTGRES_APP:", "OK" if ok else "KO")
except Exception as e:
    print("POSTGRES_APP: KO", type(e).__name__, "SQLSTATE", getattr(e, "sqlstate", None))
PY
```

Ne pas recopier `str(e)` à l'aveugle (peut contenir une URI). `OperationalError` avec SQLSTATE `None` n'est **pas**, à lui seul, un défaut de mot de passe ; `28P01` indique un refus d'authentification PostgreSQL.

### SQL de première intention (lecture seule, sous identité applicative)

Les états éditoriaux sont contenus dans le JSONB `po_entity.content` pour `kind='treatment'`. Une inspection globale sans filtrage tenant est à proscrire en multi-tenant. Exemple sûr d'agrégats paramétrés :

```bash
~/editorial-runtime/current/.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
import psycopg
c = dotenv_values(Path.home() / "editorial-runtime/private/runtime.env")
with psycopg.connect(c["PO_DATABASE_URL"], connect_timeout=5) as db:
    with db.cursor() as cur:
        cur.execute("""
            SELECT content->>'status' AS status, count(*)
            FROM po_entity
            WHERE tenant_id=%s AND kind='treatment' AND NOT deleted
              AND content->>'type'='editorial_run'
            GROUP BY content->>'status'
            ORDER BY content->>'status'
        """, (c["EDITORIAL_TENANT_ID"],))
        for state, count in cur.fetchall():
            print(state, count)
PY
```

Ne pas afficher `content`, `raw_response`, `prompt` dans les diagnostics standard. Pour un run unique, utiliser `scripts/diagnose_editorial_run.py --run-id <UUID>` seulement après vérification de sa configuration, ou l'API authentifiée et le schéma exact.

## 5. Qwen, llama.cpp, Vulkan et le réseau WSL↔Windows

**À distinguer :** `llama-server.exe` héberge le modèle et son API HTTP ; **Vulkan** sert de backend de calcul GPU. `-ngl 99` demande l'offload ; vérifier dans les logs le nombre de couches réellement transférées, la VRAM et les erreurs, et non uniquement `--list-devices`.

**PowerShell Windows (PAS Bash Ubuntu)** :

```powershell
Test-Path "C:\IA\llama.cpp\llama-server.exe"
Test-Path "C:\IA\llama.cpp\ggml-vulkan.dll"
& "C:\IA\llama.cpp\llama-server.exe" --list-devices
Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, OwningProcess
Get-Process | Where-Object { $_.ProcessName -match 'llama|ollama|lmstudio|qwen' } |
  Select-Object ProcessName, Id
# Ne pas supposer que llama-server écoute sur 127.0.0.1 :
# dans l'incident, il écoutait sur l'IP Windows/WSL (172.31.48.1).
$listener = Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue
$address = $listener | Where-Object { $_.LocalAddress -notin @('0.0.0.0','::') } |
  Select-Object -First 1 -ExpandProperty LocalAddress
if (-not $address -and $listener) { $address = '127.0.0.1' }
if ($address) { curl.exe --max-time 8 "http://${address}:8081/v1/models" }
```

Ces chemins correspondent à l'installation observée ; sinon retrouver l'exécutable sans télécharger/réinstaller le modèle. Ne pas démarrer une deuxième instance sur le même port.

**Bash Ubuntu WSL** :

```bash
ip -4 route show default
# Tester l'adresse ACTUELLE vue par WSL, pas une valeur copiée d'un incident antérieur.
# Pendant INC-2026-10-14, 172.31.48.1 répondait :
curl --max-time 15 -sS http://172.31.48.1:8081/health
curl --max-time 15 -sS http://172.31.48.1:8081/v1/models
```

**Démarrage conditionnel après validation des chemins, du port libre et de l'adresse Windows :**

```powershell
cd C:\IA\llama.cpp
.\llama-server.exe -hf "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M" -ngl 99 -c 4096 --host <IP_WINDOWS_ACCESSIBLE_DEPUIS_WSL> --port 8081
```

L'adresse `<IP_WINDOWS_ACCESSIBLE_DEPUIS_WSL>` est un **espace réservé** à remplacer. L'IP peut changer à chaque redémarrage de WSL ; ne pas ouvrir largement le port à Internet. Vérifier les logs `model loaded` et `listening on ...`, puis `/health` depuis WSL. Garder le processus vivant pour la recette.

**Smoke Qwen réel (génère du texte, aucune écriture en base ; Bash Ubuntu)** :

```bash
curl -sS --max-time 120 http://172.31.48.1:8081/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Réponds uniquement : Test MCO."}],"max_tokens":48,"temperature":0}'
```

Comparer l'adresse à `LLM_BASE_URL` effective dans la configuration ; ne pas révéler ses éventuels paramètres/jetons.

## 6. Studio : authentification privée et routes

Configuration permanente réelle : `~/editorial-runtime/private/runtime.env`, liée par `~/editorial-runtime/current/.env`. Ne jamais éditer un `.env` dans une release immutable.

**Présence des paramètres, sans secrets :**

```bash
~/editorial-runtime/current/.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
c = dotenv_values(Path.home() / "editorial-runtime/private/runtime.env")
for k in ("PO_DATABASE_URL","LLM_BASE_URL","EDITORIAL_API_TOKEN",
          "EDITORIAL_TENANT_ID","EDITORIAL_ACTOR_ID","EDITORIAL_WEB_PASSWORD"):
    print(k, "OK" if c.get(k) else "ABSENT")
password, token = c.get("EDITORIAL_WEB_PASSWORD", ""), c.get("EDITORIAL_API_TOKEN", "")
print("STUDIO_SECRET_VALID:", len(password) >= 32 and password != token)
print("ASYNC_ENABLED:", c.get("EDITORIAL_ASYNC_ENABLED") or "false")
PY
```

Studio mono-identité privée : session en mémoire, cookies HttpOnly / SameSite, contrôle Origin/CSRF. `401` = session non authentifiée ; `403` = contrôle origine/CSRF ou accès non local ; `429` = limitation de connexion ; `503` = config/dépendance ; `404` sur `/studio` dans un serveur sain = vérifier la release. **Ne pas divulguer le mot de passe dans le ticket.**

## 7. Sauvegarde PostgreSQL — méthode validée par l'incident

Le `pg_dump` exécuté par `docker exec` sans mot de passe, ou en utilisant uniquement `POSTGRES_PASSWORD` du conteneur, a échoué par `fe_sendauth: no password supplied`. La solution réussie lit **en mémoire** les identifiants de `PO_DATABASE_URL` sans les journaliser, passe le mot de passe via stdin, et vérifie une archive PostgreSQL au format custom.

> **Action avec création de fichier** (aucune mutation des données de la base). Vérifier avant l'espace disque, le destinataire du dump et les permissions. Ne pas copier le dump dans le dépôt.

```bash
~/editorial-runtime/current/.venv/bin/python - <<'PY'
from pathlib import Path
from datetime import datetime
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict
import subprocess, tempfile, os

root = Path.home() / "editorial-runtime"
c = dotenv_values(root / "private/runtime.env")
db = conninfo_to_dict(c["PO_DATABASE_URL"])
password = db.get("password")
if not password:
    raise SystemExit("SAUVEGARDE: mot de passe non disponible dans la configuration")
folder = root / "backups"
folder.mkdir(mode=0o700, parents=True, exist_ok=True)
folder.chmod(0o700)
fd, temp = tempfile.mkstemp(prefix=".editorial-", suffix=".dump", dir=folder)
backup = folder / ("editorial-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".dump")
try:
    with os.fdopen(fd, "wb") as output:
        result = subprocess.run(
            ["docker", "exec", "-i", "editorial-postgres", "sh", "-c",
             'IFS= read -r PGPASSWORD; export PGPASSWORD; exec pg_dump -w -U "$1" -d "$2" -Fc',
             "backup", db.get("user", "editorial"), db.get("dbname", "editorial")],
            input=password + "\n", text=True, stdout=output, stderr=subprocess.PIPE
        )
    if result.returncode != 0 or os.path.getsize(temp) == 0:
        raise RuntimeError("pg_dump a échoué")
    with open(temp, "rb") as archive:
        check = subprocess.run(
            ["docker", "exec", "-i", "editorial-postgres", "pg_restore", "-l"],
            stdin=archive, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
    if check.returncode:
        raise RuntimeError("pg_restore -l a échoué")
    os.replace(temp, backup)
    print("SAUVEGARDE: OK")
    print("TAILLE_KIO:", round(backup.stat().st_size / 1024, 1))
    print("ARCHIVE_LISIBLE: OK")
except Exception as e:
    print("SAUVEGARDE: ECHEC", type(e).__name__)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
PY
```

**Points de prudence :** le test `pg_restore -l` prouve la lecture du catalogue, **pas** la restauration effective. L'incident a produit une archive ~26,7 Ko ; taille non suffisante pour affirmer l'intégrité des données. Faire ensuite une restauration **dans une base PostgreSQL jetable**, contrôler objets, échantillons/volumes métier, puis détruire seulement cette base de test. Un redirection `> backup.dump` peut laisser un fichier vide lors d'un `pg_dump` échoué : lister les archives vides (`find ~/editorial-runtime/backups -maxdepth 1 -name '*.dump' -size 0 -print`) avant de sélectionner une sauvegarde.

## 8. GitHub Actions : skipped, startup_failure, vraie livraison

**Workflow :** `.github/workflows/local-delivery.yml` :
- `workflow_run` à la fin de **Full regression** ;
- sous-condition `LOCAL_PC_ENABLED=true`, CI réussie venant d'un `push` sur `main` du même dépôt ;
- runner privé `self-hosted`, `Linux`, `editorial-pc` ;
- `LOCAL_RELEASE_ROOT` et `LOCAL_CONFIG_PATH` présents ; test PostgreSQL jetable puis `scripts/deploy_local.py` ;
- approval explicite du SHA **avant** toute activation/relance.

**Matrice des symptômes :**

| État GitHub | Signification possible | Diagnostic/recours |
| --- | --- | --- |
| `skipped` | Condition `if` fausse ; notamment flag à `false` au moment pertinent, mauvais événement/branche. | Vérifier le YAML, le SHA, l'événement initial ; runner `Idle` n'est pas la cause d'un job ignoré. |
| `queued` | Événement accepté, travail non démarré. | Attendre puis inspecter jobs / runner Online et labels. Ne pas annoncer une release installée. |
| `startup_failure` sans job | GitHub n'a pas démarré le job ; **cause exacte inconnue** pour l'ancien run. | Ne pas inférer un bug Qwen/DB. Examiner le run ; pendant cet incident relancer **Full regression du même SHA** a créé un nouvel événement valide. |
| `success` sur Full regression | Code testé en CI, **pas encore installé sur le PC**. | Attendre le nouveau `Private PC delivery`. |
| `success` sur install-and-live | Candidate + tests HTTP et bascule ont réussi ; vérifier le SHA local et reçu pour l'attester. | `current`, `last_delivery.json`, PID systemd, routes live. |

Incident : `Full regression #38635895291` (relance du SHA `07f99edb`) a généré `Private PC delivery #38653094752` **success**. La relance de l'ancien `#38636002145` était `skipped` puis `startup_failure` ; n'en tirer aucune théorie causale supplémentaire.

**Après MEP**, vérifier dans GitHub Settings → Actions → Variables que `LOCAL_PC_ENABLED=false`. **Ne pas fusionner d'autres PR tant que cette garde est ouverte**, car un push `main` suivi d'une CI verte pourrait automatiquement livrer un autre SHA non autorisé.

## 9. Recette après correction et critères de sortie

1. Comparer SHA autorisé, `origin/main`, `current`, reçu et répertoire de travail du PID systemd.
2. `GET /health=200`, `GET /ready=200`, `GET /studio=200` (codes si mode sync et dépendances disponibles).
3. PostgreSQL : `pg_isready` + authentification applicative + `SELECT 1`.
4. Qwen : `/v1/models`, `/health` et requête de génération courte, puis vérification des logs Vulkan si l'offload GPU est exigé.
5. Studio live : anonyme non authentifié, connexion, bibliothèque, création d'un bref scénario (test technique identifié), analyse, storyboard, `/history`, idempotence, déconnexion ; vérifier les données en base.
6. Recette produit distincte : approbation/rejet/révision, conflits 409, erreurs 401/422/503, navigation mobile, comportement après redémarrage et conservation des traces.
7. Sauvegarde contrôlée et **test de restauration isolé** si risque base.
8. Désactiver `LOCAL_PC_ENABLED` après MEP, consigner résultats/limites et horodatage dans le ticket.

La CI navigateur `browser_checks/test_studio_browser.py` utilise une fixture simulée, même si Chromium est réel. Elle ne remplace pas la recette manuelle sur la version installée. Ne pas annoncer une fonction publication ou génération d'images/vidéos qui n'est pas implémentée.

## 10. Risques de reprise et escalade

- **Worker :** `EDITORIAL_ASYNC_ENABLED` absent/`false` = worker inactif attendu. Si `true` mais pas de worker enregistré, création renvoie 503 et `/ready` dégradé (JOB-001) : démarrer/qualifier le worker, ne pas désactiver la sécurité.
- **Run `running` >10 min / échec réseau :** diagnostiquer état et snapshots ; `reconcile` seulement après vérification, ne jamais relancer Qwen automatiquement pour un résultat incertain.
- **Après reboot :** vérifier Docker, Qwen Windows, WSL, service systemd et runner ; un service `disabled` ou un serveur lancé dans une console interactive peut s'arrêter.
- **Rollback :** seul le mécanisme de release `scripts/deploy_local.py` est autorisé à basculer `current` avec vérification ; un retour arrière de code **ne restaure pas** une migration SQL.
- **Échec répété :** conserver diagnostic, journaux filtrés, SHA, gravité et blocage ; ne pas multiplier des corrections spéculatives. Toute corruption de volume, impossibilité de restaurer ou fuite de secret = escalade immédiate.

Références : [incident d'octobre 2026](INCIDENT_2026-10-14_REMISE_EN_SERVICE_PC.md), [index et modèle de ticket](README.md), [livraison](../AUTONOMOUS_DELIVERY.md), [Studio](../STUDIO_PRIVATE.md), [worker](../ASYNC_EDITORIAL_WORKER.md).
