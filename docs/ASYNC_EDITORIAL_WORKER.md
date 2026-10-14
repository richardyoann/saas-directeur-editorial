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
- `/health` = liveness locale ; `/ready` = disponibilité simultanée PostgreSQL + `LLM_BASE_URL/health` (HTTP 200). **`/ready` ne prouve pas que le worker tourne**.
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
