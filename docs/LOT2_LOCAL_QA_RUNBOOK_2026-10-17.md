# Recette locale du Lot 2 — vérification complète sans accès à la production

**Statut : scripts et tests proposés dans PR #198, non déployés.** Tout parcours PostgreSQL ci-dessous utilise une instance **jetable séparée**, jamais la base, les volumes ni les variables de production. Ne jamais lancer `scripts/run_regression.py` avec `PO_TEST_DATABASE_URL` pointant sur la base métier.

## Mettre à jour la copie de test

Depuis WSL (si le worktree précédent ne contient pas de modifications locales) :

```bash
cd ~/arvor-crew-check
git status --short
git fetch origin
git switch --detach origin/feature/production-crew-quality-gate-20261017
git rev-parse HEAD
```

Ne pas forcer le checkout en cas de modifications : faire un worktree distinct. La révision du code de test ne change pas la version installée sur PC.

## A — Régression PostgreSQL jetable

Équivalent du workflow CI : `postgres:16`, compte et DB `po_test`, port local *distinct* 55432, données éphémères en tmpfs ; pas de `docker compose`, pas de volumes réutilisés, aucun secret applicatif.

```bash
bash -euo pipefail <<'BASH'
cd ~/arvor-crew-check
docker image inspect postgres:16 >/dev/null
container="arvor-crew-test-$$"
docker run -d --rm --pull=never --name "$container" \
  --tmpfs /var/lib/postgresql/data:rw,size=1024m,mode=0700 \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=po_test \
  -e POSTGRES_PASSWORD=ephemeral_ci_only \
  -e POSTGRES_DB=po_test postgres:16 >/dev/null
trap 'docker stop "$container" >/dev/null 2>&1 || true' EXIT
ready=0
for i in $(seq 1 30); do
  if docker exec "$container" pg_isready -U po_test -d po_test >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
test "$ready" -eq 1
export PO_TEST_DATABASE_URL="postgresql://po_test:ephemeral_ci_only@127.0.0.1:55432/po_test"
export TRACE_TEST_DATABASE_URL="$PO_TEST_DATABASE_URL"
export PO_ALLOW_TEST_MIGRATION=yes
~/editorial-runtime/current/.venv/bin/python scripts/prepare_test_database.py
~/editorial-runtime/current/.venv/bin/python scripts/run_regression.py
BASH
```

**Validation :** zéro échec, erreur et skip. Si `docker image inspect` échoue, l'image locale n'existe pas : ne pas lancer de téléchargement/install sans vérification. Ne jamais réutiliser le mot de passe `ephemeral_ci_only` sur un serveur exposé ; il sert uniquement à la DB jetable liée à loopback.

## B — Qwen réel, sans écrire dans PostgreSQL

Le script `scripts/verify_production_crew_real.py` est **strictement sans stockage**, utilise un brief fictif de 75 s et n'affiche que les états, durées et note du Critique. Il refuse les URL publiques, les identifiants dans l'URL et les redirections. Aucun retry ; un échec arrête la campagne.

Le moteur local doit déjà être en cours d'exécution. La variable `LLM_BASE_URL` doit provenir de la configuration privée actuelle (exemple fictif de format : `http://127.0.0.1:8080`, port à vérifier sur PC).

```bash
# Contrôle rapide d'un seul métier : un seul appel Qwen
~/editorial-runtime/current/.venv/bin/python scripts/verify_production_crew_real.py

# Puis sept rôles séquentiels, SEULEMENT après le premier succès.
~/editorial-runtime/current/.venv/bin/python scripts/verify_production_crew_real.py --all
```

L'alternative `--url 'http://HOTE_PRIVE:PORT'` est possible si `LLM_BASE_URL` n'est pas exportée. Ne pas copier les secrets dans GitHub ni les rapports. `all_requested_steps_valid=true` signifie que le vrai fournisseur a renvoyé des structures valides pour les rôles demandés. La note critique n'est pas un résultat de contrôle visuel d'images ou d'un MP4.

## C — Chromium réel avec API factice, sans installation

D'abord vérifier la présence du pilote Playwright et du navigateur **Linux** :

```bash
~/editorial-runtime/current/.venv/bin/python -c "import importlib.util; print('playwright_present=',importlib.util.find_spec('playwright') is not None)"
command -v google-chrome || command -v chromium || command -v chromium-browser || true
```

Si les deux composants existent, lancer :

```bash
STUDIO_BROWSER_TESTS=yes \
~/editorial-runtime/current/.venv/bin/python -m unittest \
  discover -s browser_checks -p 'test_studio_browser.py' -v
```

Le test navigateur démarre un serveur d'essai sur **127.0.0.1 et un port aléatoire**, avec identifiants fictifs, API simulée et aucune histoire utilisateur. Les anciens scénarios 60 s/3 scènes fixent maintenant leur format explicitement ; le nouveau scénario teste le défaut 75 s/5 scènes, l'approbation humaine et les boutons de l'équipe IA (sans Qwen réel). Si Playwright ou Chrome Linux manquent, **ne pas installer automatiquement** : qualifier d'abord la disponibilité des paquets et le besoin d'une installation explicite.

## Conclusion et preuves

Ces trois campagnes sont indépendantes : PostgreSQL contrôle les transactions réelles sur base de test ; Qwen teste les sorties de modèle sur scène fictive, sans persistance ; Chromium vérifie l'ergonomie avec API simulée. Elles ne suffisent pas à déclarer la production vidéo complète : il reste à tester le pipeline réel réunissant Qwen, PostgreSQL, images SD.cpp, audio, FFmpeg et critique multimodale, sans utiliser de données de production, ainsi que la revue humaine.

Aucune de ces commandes ne déploie la branche ou ne modifie l'installation du PC.
