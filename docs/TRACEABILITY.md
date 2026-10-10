# DEV-004 — POC audit / outbox / Slack

## État vérifié le 10 octobre 2026

Dépôt privé confirmé : `richardyoann/saas-directeur-editorial`, ID `1411435489`.
Base inspectée : `main`, commit `caf1725ad0087fee1a78e078047de6382d210f39`.
Copie locale figée récupérée via GitHub ; aucun checkout WSL inspecté et aucune
preuve sur ses changements non poussés. La copie locale n'a pas de métadonnées Git.

Slack connecté : espace `T0C7ZUAM4DR`, canal `C0C883XR3DF`,
List `F0C83UZ4XHB`. EPIC-001 et DEV-001 lus. La List refuse l'ajout DEV-004
avec `no_permission_to_edit_list` ; les messages de suivi dans le canal fonctionnent.
Le statut DEV-001 dans Slack diverge de l'état historique du dépôt : à réconcilier
avec une preuve actuelle, sans clôture automatique.

## Ce que le POC fait

- `trace_work_item` représente Epic → Story → tâche → sous-tâche. IDs immuables,
  parent du niveau précédent, version optimiste pour changements de statut.
- `trace_audit` append-only par trigger et `trace_outbox` sont écrits dans la
  même transaction que le changement d'un élément. Rollback annule les trois.
- `source_key` unique déduplique créations/replays et livraisons GitHub.
  Réutiliser une clé avec des données différentes provoque un conflit.
- UUID événement et corrélation transportés vers Slack ; la réponse HTTP porte
  `X-Correlation-ID`. Le webhook utilise l'UUID de livraison GitHub comme corrélation.
- `/trace/github` vérifie HMAC SHA256 sur le corps brut, impose le dépôt et son ID,
  limite le corps à 1 MiB, et extrait les IDs du titre/corps des PR sans conserver
  ces textes. Les actions PR prises en charge sont énumérées dans `events.py`.
- `/ai/generate` journalise demande et résultat si `TRACE_ENABLED=1`. Une panne
  audit avant l'appel bloque la génération (503). Une panne après l'appel renvoie
  503 avec corrélation : le modèle a pu répondre ; inspecter avant de relancer.
- Redaction structurelle : seules des métadonnées typées et autorisées sont
  conservées. Les champs libres/secrets sont refusés avant audit et envoi ;
  aucun prompt, résultat, titre, corps, URL, header ou exception brute n'est publié.
  Ce POC ne remplace pas un coffre de secrets et n'importe pas le journal JSONL.
- Worker : réservation durable `sending`, `FOR UPDATE SKIP LOCKED`, 8 tentatives
  maximum, backoff, prise en compte de 429 / Retry-After, erreurs normalisées.
  Une réponse ambiguë, read/write timeout, HTTP 5xx ou crash après réservation
  donne `uncertain`, jamais une retransmission automatique aveugle.

## Idempotence et limites

La base garantit un événement/outbox par clé source. Le worker ne renvoie pas
les événements `sent` ; deux workers ne peuvent réserver simultanément la même
ligne. `client_msg_id` et metadata portent l'UUID, sans présumer une garantie
Slack exactly-once. L'absence d'une transaction distribuée PostgreSQL/Slack
impose une réconciliation en cas d'accusé de réception perdu.

`python -m traceability.operations status` affiche les états. Pour un `uncertain`,
retrouver le message dans Slack par event_id puis :

```text
python -m traceability.operations confirm-sent EVENT_UUID SLACK_TS
```

Le script vérifie timestamp, canal et metadata via l'historique avant de marquer
`sent`. Une absence de preuve ne signifie pas une absence de livraison. Une
reprise manuelle explicite après inspection est possible avec `retry EVENT_UUID
--acknowledge-duplicate-risk` ; elle peut produire un doublon. Surveiller
`uncertain`, `dead`, l'âge des `pending`, et demandes de génération sans résultat.
Le worker est borné à 100 éléments par invocation ; aucun superviseur déployé.

## Configuration et lancement

Installer `requirements.txt` dans un environnement dédié. Configuration par
variables du processus/coffre, sans ajouter de secrets aux fichiers versionnés :

| Variable | Usage |
| --- | --- |
| TRACE_DATABASE_URL | PostgreSQL migré, rôle applicatif limité |
| TRACE_API_KEY | Clé des endpoints de gestion ; absente = 503 |
| TRACE_GITHUB_WEBHOOK_SECRET | Secret HMAC ; absent = webhook 503 |
| TRACE_ENABLED | `1` pour auditer la génération ; défaut désactivé |
| TRACE_SLACK_BOT_TOKEN | Token du worker, `chat:write`, accès au canal |
| TRACE_SLACK_CHANNEL | Destination imposée `C0C883XR3DF` |
| TRACE_TEST_DATABASE_URL | Base dédiée déjà migrée, uniquement tests |

La connexion Slack de ChatGPT ne fournit pas au processus FastAPI son token.
Un bot du bon espace doit être configuré séparément et son identité vérifiée
avant activation. La réconciliation nécessite les droits d'historique appropriés.

Après revue/accord, appliquer `migrations/001_traceability.sql` à la base cible.
Cette migration n'est pas réexécutable et n'est jamais lancée par l'API.
Restreindre audit à SELECT/INSERT pour l'API ; interdire UPDATE/DELETE/TRUNCATE.
L'owner PostgreSQL peut contourner les triggers : ce n'est pas un audit inviolable.
Lancer l'API comme auparavant puis `python -m traceability.worker` via un
superviseur. Configurer un webhook PR vers `/trace/github` uniquement après
déploiement privé HTTPS et vérification du secret. Aucun webhook distant créé ici.

Exemple de création avec client authentifié :
`POST /trace/work-items` avec `{"id":"EPIC-001","kind":"epic","status":"in_progress"}`,
puis `{"id":"DEV-004","kind":"story","parent_id":"EPIC-001"}`.
La clé est transmise en header `X-Trace-Key`. La mise à jour utilise
`PATCH /trace/work-items/DEV-004`, statut et `expected_version` ; une version
obsolète retourne 409. Rejouer une création identique retourne le même event_id.
Les modifications manuelles de Slack List ne sont pas importées automatiquement.

## Preuves et ce qui reste ouvert

`validation/results.json`, `trace.txt`, `generation.txt`, `full_windows.txt`
conservent les résultats réellement exécutés avec Python 3.12 sous Windows.
16 tests POC réussis, dont 5 sur un PostgreSQL 16 réel dédié : rollback,
déduplication, hiérarchie/version, concurrence, crash et FastAPI → audit/outbox
(réponse du modèle simulée). Six tests historiques génération réussis.
Suite complète Windows : 48 tests/entrées, 32 réussis, 14 erreurs, 2 échecs,
liés à `fcntl`, `O_NOFOLLOW` et privilèges symlink. La suite complète n'est pas verte.

Migration appliquée avec accord uniquement à `trace_test` sur localhost:55432,
conteneur `editorial-trace-test-01a125c4`, sans toucher aux services du SaaS.
Les tests PostgreSQL conservent leurs lignes et décalent les pending pour isoler
le worker ; ne jamais les lancer sur une base contenant des données utiles.

Pas de test du worker avec un vrai token Slack, pas d'appel réel Qwen,
pas de déploiement, pas de migration métier/production, pas de synchronisation
automatique Slack List, pas d'isolation multi-tenant. Les IDs extraits des PR sont
des références déclarées ; leur existence dans le backlog n'est pas garantie.
Les autres événements métier doivent appeler `emit` dans leur transaction de
persistance et ajouter contrat/tests ; ils ne sont pas inventés ici.

Références : [Slack chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/),
[signature GitHub](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries),
[verrous PostgreSQL](https://www.postgresql.org/docs/16/sql-select.html).
