# MCO — Surveillance passive de la file éditoriale (JOB-001)

## Objectif et périmètre

Le garde-fou existant `/ready` détecte une absence de worker enregistré en
mode asynchrone. Son verrou PostgreSQL **ne prouve pas que Qwen progresse** :
un worker connecté peut être bloqué, ou des histoires peuvent rester en attente.
Le script `scripts/diagnose_editorial_queue.py` complète ce contrôle par une
**photo instantanée et non intrusive** du backlog.

Il lit uniquement des agrégats `po_entity` du tenant privé configuré :
`queued`, `running`, `failed`, `waiting_validation`,
`changes_requested`, `approved` et `other`. Il affiche les totaux,
l'ancienneté maximale de `queued` / `running` et des codes d'alerte fixes.
Les statuts inattendus sont regroupés dans `other` plutôt que réaffichés.

**Jamais** de prompts, réponses, titres, UUID de run, URL de base, clés ou
exception brute dans la sortie. Il n'y a ni création/mutation en base, ni
verrou de job, ni POST HTTP, ni appel Qwen, ni nouveau package/migration.

## Exécution sur une release qui contient le script

Après validation et livraison du SHA correspondant, depuis Ubuntu 26.04 :

```bash
cd ~/editorial-runtime/current
.venv/bin/python scripts/diagnose_editorial_queue.py
echo "code_retour=$?"
```

La configuration existante doit fournir `PO_DATABASE_URL` et
`EDITORIAL_TENANT_ID` via les variables de processus ou le fichier `.env`
**privé de cette release**. Ne jamais publier ces valeurs, même pour diagnostiquer.
Le programme refuse une identité tenant absente ou incorrecte.

Pour régler les seuils **sans réécrire de configuration** :

```bash
.venv/bin/python scripts/diagnose_editorial_queue.py \
  --queued-seconds 300 --running-seconds 600
```

Le mode historique synchrone peut lui aussi contenir des exécutions `running`.
Le script ne dépend pas du démarrage d'un worker et n'affirme pas que celui-ci
est sain. Les seuils sont indicatifs, **pas une preuve d'échec Qwen**.

## Sortie JSON et exploitation

- `status=ok`, code de sortie **0** : aucun retard mesurable à l'instant de la
  lecture ; ne prouve pas que les services ou le worker sont disponibles.
- `status=alert`, code **2** : `queued_overdue` si l'attente la plus ancienne
  atteint 300 secondes, `running_stale` au-delà de 600 secondes ; si une date
  est absente, invalide, sans fuseau ou trop future, `*_age_unknown`.
- `status=unavailable`, code **3** : configuration inaccessible ou connexion /
  donnée invalide. Le message d'erreur réel n'est jamais imprimé car certaines
  exceptions incluent des secrets.

Exemple **fictif** :

```json
{
  "alerts": ["running_stale"],
  "counts": {
    "approved": 2,
    "changes_requested": 0,
    "failed": 1,
    "other": 0,
    "queued": 0,
    "running": 1,
    "waiting_validation": 3
  },
  "oldest_age_seconds": {"queued": null, "running": 795},
  "status": "alert",
  "thresholds_seconds": {"queued": 300, "running": 600},
  "total_runs": 7
}
```

En cas d'alerte : vérifier `/ready`, `editorial-worker.service`, PostgreSQL,
le temps GPU/Qwen et l'historique du run via l'API privée. Pour un `running`
vraiment interrompu, employer **uniquement** la réconciliation explicite
`/studio/api/runs/{uuid}/reconcile`, avec session/CSRF et âge suffisant.
**Ne pas redémarrer automatiquement une génération incertaine** ; conserver
l'idempotence et la revue humaine.

La mesure n'est ni un heartbeat durable, ni un daemon, ni un système d'alerte
poussé vers Slack. Avant d'automatiser une notification, prévoir anti-doublons,
contrôle d'accès et politique de rétention; ne transmettre que des compteurs et
codes de statut, jamais les données des histoires.

## Contrôles et limites

```bash
.venv/bin/python -m unittest tests.test_diagnose_editorial_queue -v
.venv/bin/python -m unittest discover -s tests -v
```

Les tests unitaires simulent les erreurs et dates ambiguës ; un test
d'intégration supplémentaire exécute la vraie agrégation sur PostgreSQL 16
**jetable**, avec deux tenants distincts et un run en cours / en attente.
Il ne s'exécute que si `PO_TEST_DATABASE_URL` est renseignée ; les créations
de schéma nécessitent `PO_ALLOW_TEST_MIGRATION=yes`. Ne jamais utiliser la
base PC comme cible de ces tests mutables. Une CI réussie ne prouve **pas** une
lecture de la base utilisateur : valider la commande sur le PC privé après
accord sur le SHA exact. Les index JSONB optimisés restent
reportés à une mesure représentative avant migration. La requête agrégée peut
balayer les runs d'un tenant : exécuter à une fréquence modérée, pas en boucle
rapprochée.

**Retour arrière :** ne pas exécuter le script ou supprimer cet incrément lors
d'une future release. Aucun état métier à annuler.
