# Worker éditorial asynchrone — livraison préparatoire

## Motivation et choix de fiabilité

L'API actuelle effectue deux appels Qwen dans la requête HTTP, ce qui immobilise l'interface lors des générations. Cet incrément ajoute une **file durable PostgreSQL** utilisant le même magasin de runs/audit/outbox, un worker distinct et un suivi des états dans Studio. Aucun événement de tâche ne peut être perdu entre une écriture métier et un push vers une file externe, puisqu'il n'y a **pas de double écriture Redis + DB**. Redis reste dans Compose mais n'est pas nécessaire à cet incrément.

Ce choix privilégie la simplicité pour le MVP privé, et ne prétend pas remplacer un ordonnanceur multi-tenant à grande échelle.

## Contrats

- Mode classique par défaut : `EDITORIAL_ASYNC_ENABLED=false` (ou absent), `POST /editorial/runs` continue à répondre avec le résultat après la génération.
- Mode asynchrone, **uniquement après installation et qualification du worker** : `EDITORIAL_ASYNC_ENABLED=true`; `POST /editorial/runs` persiste une entrée `queued` et répond immédiatement HTTP **202**, avec UUID immuable ; un doublon d'idempotence renvoie le même run sans nouveau calcul.
- Un worker exécute `claim_queued` avec `FOR UPDATE SKIP LOCKED` puis traite `analysis` et `storyboard` via le service existant. Les prompts, résultats, versions, audit et outbox sont conservés comme avant.
- L'interface vérifie uniquement le run ouvert toutes les 4 secondes, tant que l'onglet est visible et l'état `queued`/`running`. Elle n'envoie jamais de demande de génération supplémentaire.
- Échec du processus après la prise en charge : run `running` conservé, l'opérateur utilise la réconciliation explicite existante après dix minutes ; **aucun rejeu automatique ambigu**.
- `/health` = liveness locale ; `/ready` = disponibilité simultanée PostgreSQL + `LLM_BASE_URL/health` (HTTP 200) **et, seulement en mode asynchrone, présence d'un worker enregistré**. Le verrou de session worker n'atteste pas de sa progression effective.
- Les clients HTTP Qwen et façade ASGI sont partagés **par processus au démarrage** et fermés à l'arrêt via le lifespan FastAPI. Les tests unitaires sans lifespan ont un fallback temporaire.

## Installation PC — non exécutée

1. Vérifier que le service FastAPI et le worker partageront **la même release immuable**, le même `.env`, et un environnement Python valide. Ne pas utiliser plusieurs workers Qwen sans dimensionner GPU/VRAM.
2. Démarrer et superviser séparément le worker avant de basculer le flag API. Commandes de qualification **manuelles uniquement** depuis la release candidate :
   ```bash
   # Configurer PO_DATABASE_URL, EDITORIAL_TENANT_ID, EDITORIAL_ACTOR_ID,
   # EDITORIAL_API_TOKEN, LLM_BASE_URL et EDITORIAL_ASYNC_ENABLED=true
   .venv/bin/python -m workers.editorial_worker --once
   ```
   `--once` réclame au maximum une tâche et quitte (il ne génère aucun contenu sans tâche). Pour un fonctionnement continu, exécuter `.venv/bin/python -m workers.editorial_worker` avec un service systemd utilisateur dédié, `Restart=on-failure`, arrêt propre, et un journal sans prompt ni secret.
3. Qualifier **sur base et Qwen réels** une génération complète et deux demandes concurrentes, puis un redémarrage worker avec une demande encore `queued`. Vérifier run, snapshots, audit et absence de doublon. Si le processus crash après la prise, utiliser réconciliation manuelle, ne pas retenter aveuglément.
4. Confirmer la stabilité de la supervision worker avant de configurer `EDITORIAL_ASYNC_ENABLED=true` sur le serveur FastAPI et le redémarrer. Ne pas exposer l'API à Internet.
5. Surveiller au minimum : nombre de `queued`, âge du plus ancien run, `running` depuis > 10 minutes, taux d'échec LLM, durée des tâches, consommation GPU. Une API saine peut coexister avec un worker arrêté.
6. **Rollback fonctionnel** : repasser `EDITORIAL_ASYNC_ENABLED=false` puis redémarrer uniquement l'API, laisser le worker traiter/vider les jobs persistés si possible. Un run déjà `queued` ne sera pas exécuté par l'ancienne route sync ; ne jamais supprimer des jobs en base. Contrôler séparément le service worker et les traces.

Le workflow GitHub de livraison PC n'a volontairement pas été modifié pour activer le flag ou démarrer un worker. Il faut une recette et une validation de l'installation autonome avant cette bascule.

## Limites et étapes suivantes

- À ce stade le polling DB toutes les secondes par **worker**, et l'interface toutes les 4 secondes, sont adaptés au seul utilisateur privé. Pour un SaaS multi-utilisateur, ajouter quotas, monitoring distribué, état de vie du worker, mécanisme de réveil Redis/outbox, rôle DB à privilèges minimaux et politiques d'isolation.
- Le modèle `po_entity` reste générique ; seul le listing lit maintenant des champs ciblés `content->...` au lieu de transférer tout le storyboard. Les index d'expression sont documentés mais ne sont **pas appliqués sur la base PC**.
- Revoir le timeout GPU et les transitions en charge, puis écrire la machine à états formelle avant un worker en production multi-client.
- Ne pas partager les résultats IA mis en cache entre tenants. Une future clé de cache doit inclure tenant, identité du modèle, version du prompt et normalisation du brief, avec des règles de rétention conformes RGPD.

## Tests et critères d'acceptation

- PostgreSQL jetable : création `queued`, même clé = même run, `SKIP LOCKED` entre deux workers, isolation tenant, audit/outbox atomiques.
- API isolée : `POST` renvoie 202 sans LLM et la relance idempotente aussi ; worker génère deux étapes ; mode sync non régressé.
- Chromium : statut `En attente` puis `En cours` et `À valider` via polling sans deuxième POST.
- Liveness/readiness : échec DB ou Qwen rend `/ready` indisponible ; aucune fuite de chaîne de connexion.
- Tests de régression, sécurité et revue de code obligatoires au **SHA exact** avant fusion ; recette Qwen réelle et approbation de livraison distinctes.


## Correctif JOB-001 — Refus explicite si worker absent (14/10/2026)

**Défaut vérifié dans le code précédent :** en plaçant `EDITORIAL_ASYNC_ENABLED=true` dans l'API sans démarrer le worker, toute nouvelle histoire obtenait HTTP 202 et restait `queued` indéfiniment. Le service API pouvait également afficher `/ready` à 200 sans consommateur de file actif.

**Correction livrée le 14/10/2026 au SHA `07f99edbec1374af6a929aa814169d32efa6ef3a` :** le worker conserve un **verrou consultatif PostgreSQL de session par tenant** durant sa vie. Aucun schéma, Redis, migration ou secret supplémentaire n'est nécessaire. Lorsqu'une requête de création arrive en mode asynchrone, le backend vérifie dans **la même transaction** qu'un worker détient ce verrou. Si aucun worker n'est enregistré : HTTP **503**, aucune nouvelle histoire enregistrée et aucun événement audit/outbox ajouté. Les demandes déjà enregistrées avec la même clé d'idempotence restent consultables même lorsque le worker s'arrête. Deux processus ne peuvent pas s'enregistrer comme consommateurs pour le même tenant privé.

La route `/ready` vérifie également ce verrou **uniquement lorsque le mode asynchrone est activé**. Liveness `/health` ne change pas.

**Limites** : il s'agit d'un indicateur de session de connexion PostgreSQL, pas d'une preuve de progression effective de Qwen. Une panne du modèle ou un worker bloqué peut laisser le verrou détenu ; vérifier aussi les métriques de file, les alertes et les runs anciens. L'activation doit rester sous contrôle humain après une recette PC réelle.

## Diagnostic local sans modification

Après avoir récupéré la dernière version du code dans un checkout de diagnostic (sans toucher à la release courante), depuis **WSL Ubuntu 26.04** :

```bash
cd ~/saas-directeur-editorial
.venv/bin/python scripts/diagnose_runtime.py \
  --root /home/yoann_admin/editorial-runtime \
  --expected-sha <SHA-complet-validé>
```

L'outil lit seulement le lien `current`, le reçu `last_delivery.json`, les états systemd utilisateur, la présence des paramètres de configuration et les GET loopback `/health`, `/ready`, `/studio`, `/studio/session`. Il n'affiche ni mot de passe, ni jeton, ni chaîne de connexion, ni prompts. Le chemin de runtime doit être adapté au chemin **existant** ; le script ne crée pas ce répertoire.

Interprétation : `current_sha != expected_sha` signale une release obsolète ; `/studio=404` signifie que cette release n'inclut probablement pas Studio ; `/ready=503` requiert de diagnostiquer PostgreSQL, Qwen et, si async, le worker ; `worker_service=inactive` indique qu'aucun service worker utilisateur de ce nom n'est actif. Un nom de service personnalisé requiert une vérification adaptée.

**La correction de code ne débloque pas la MEP** : `.github/workflows/local-delivery.yml` est toujours protégé par `LOCAL_PC_ENABLED`, la réussite CI et la validation explicite du SHA. Ne pas l'activer ni relancer la livraison sans cette validation. L'audit GitHub du 14/10 montre une régression verte mais une livraison PC `skipped` pour `eebec8ef`. Aucun contrôle Qwen réel de cette version ne doit être annoncé.

### Signal de réconciliation dans Studio — 22 octobre 2026

GET détail ajoute `recovery.interruption_suspected`, `reconciliation_required`
et `automatic_retry_allowed` (toujours false). Le calcul réutilise le seuil et
les timestamps de `interrupted()` ; il ne modifie pas le run et ne prouve pas
l'arrêt effectif du fournisseur. Les deux Studios affichent ce signal et
proposent uniquement la réconciliation manuelle existante. Les polls GET ne
relancent pas une tâche. Les tests de pertes PostgreSQL avant/après commit et
les limites de recette sont consignés dans
[la consolidation AUDIT-UX-01](plans/AUDIT_UX_01_CONSOLIDATION.md).
