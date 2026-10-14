# Performance PostgreSQL — mesure avant optimisation (PERF-001)

## Périmètre et précautions

Les lectures aujourd'hui paginées par tenant dans `editorial/store.py` filtrent plusieurs clés JSONB (`type`, `created_at`, `run_id`, `order`, `revision`). La table initiale ne dispose que de sa clé primaire `(tenant_id, kind, entity_id)`.

**Aucune migration de production n'est appliquée ici.** La commande ci-dessous ne travaille que sur une base éphémère explicitement autorisée, à l'aide d'une table PostgreSQL **TEMPORARY** homonyme de `po_entity`, qui disparaît à la fermeture de la connexion. Les index `benchmark_*` sont également temporaires.

```bash
export PO_TEST_DATABASE_URL='postgresql://.../base_jetable'
export PO_ALLOW_TEST_MIGRATION=yes
python scripts/benchmark_editorial_sql.py --rows 1200 --disposable
```

La CI exécute ce benchmark après la suite de tests dans le service PostgreSQL 16 jetable. Les résultats contiennent `Execution Time` mesuré en millisecondes, types de nœuds `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` et contrôle d'identité des résultats avant/après indexation. **Ne pas interpréter des gains sur un jeu synthétique comme des gains garantis en production**.

## Résultat reproductible du premier passage CI

Exécution [Full regression #38630731419](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38630731419), PostgreSQL 16, **1 200 runs / 4 800 enregistrements synthétiques**, source PR #77.

| Requête | Sans index expression | Avec index temporaire | Plan observé après |
|---|---:|---:|---|
| Catalogue (21 lignes) | 1,703 ms | 0,029 ms | Index Scan + Limit |
| Historique LLM (2 lignes) | 0,513 ms | 0,027 ms | Index Scan |
| Décisions (1 ligne) | 0,497 ms | 0,027 ms | Index Scan + Limit |

Contrôle des résultats identiques avant/après réussi. Ce sont des **temps d'exécution d'une mesure unique**, sans charge concurrente, sur jeu artificiel. N'en déduire ni facteur d'accélération garanti, ni besoin immédiat de migration du PC : la taille réelle de sa base et ses latences demeurent inconnues.

## Index candidats, uniquement après mesures sur jeu représentatif

**Lecture seule / review : ne pas exécuter ces index sur le PC sans validation de migration, sauvegarde et rollback.** PostgreSQL interdit `CREATE INDEX CONCURRENTLY` dans une transaction ; veiller à une connexion autocommit dédiée.

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_po_editorial_runs
  ON po_entity(tenant_id, (content->>'created_at') DESC, entity_id DESC)
  WHERE kind='treatment' AND content->>'type'='editorial_run' AND NOT deleted;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_po_editorial_snapshots
  ON po_entity(tenant_id, (content->>'run_id'), ((content->>'order')::integer))
  WHERE kind='result' AND content->>'type'='editorial_step_snapshot' AND NOT deleted;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_po_editorial_reviews
  ON po_entity(tenant_id, (content->>'run_id'), ((content->>'revision')::integer) DESC)
  WHERE kind='result' AND content->>'type'='editorial_review' AND NOT deleted;
```

La migration doit couvrir les versions PostgreSQL, le suivi de schéma, l'espace disque et le coût d'écriture audit/outbox. Vérifier aussi les lignes historiques concernées avant création d'index d'expression castés en integer. Mesurer `EXPLAIN (ANALYZE, BUFFERS)` sur des quantités anonymisées réalistes et comparer P50/P95, CPU et consommation.

## Pool de connexions : différer au besoin réel

`PostgresStore.connect()` ouvre une nouvelle connexion par appel. Un pool `psycopg_pool` peut réduire le coût de connexion sous charge ; son ajout introduit toutefois de l'état, un cycle de vie applicatif et des limites de taille. Le nombre de sessions actuel et le fonctionnement sur un seul utilisateur ne justifient pas de l'ajouter sans mesurer p95 et nombre de connexions actives. Tester le risque d'épuisement des connexions avant tout changement.

## Critères d'acceptation

1. Le benchmark n'utilise jamais `PO_DATABASE_URL` et refuse toute exécution sans `--disposable` et `PO_ALLOW_TEST_MIGRATION=yes`.
2. Les requêtes de liste, historique et journal de revue renvoient strictement les mêmes résultats avant/après indexation temporaire.
3. Les plans et mesures figurent dans le journal CI, sans identifiants ni contenus utilisateur.
4. Aucune DDL permanente ni index ne sont ajoutés au démarrage de l'application.
5. Décision d'indexer ou d'introduire un pool prise après analyse des volumes et mesures réelles, jamais sur seule base des temps CI.
