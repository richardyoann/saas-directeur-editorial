# OpenCode → MLflow : observabilité indépendante

Ce connecteur expérimental observe des événements JSONL produits par `opencode run --format json` et enregistre uniquement des compteurs numériques bornés dans un serveur MLflow **loopback privé**. Il ne modifie ni la CI locale, ni le superviseur, ni les workflows de livraison PC.

## Garanties

- **Aucune autorité** : jamais une porte CI, jamais un PASS, jamais une signature/validation de preuve, jamais une autorisation de fusion ou de livraison PC.
- **Confidentialité** : aucun prompt, réponse, argument/résultat d'outil, identifiant de session, secret ou log brut n'est exporté. Seuls des compteurs de catégories sont envoyés.
- **Fail-open** : une indisponibilité MLflow retourne `telemetry_unavailable` avec `quality_gate=not_evaluated` et code de sortie 0. Elle ne bloque ni ne modifie une mission.
- **Métadonnées déclaratives** : `--sha` est une métadonnée déclarée par l'opérateur, **non vérifiée** par le bridge. Aucune valeur de confiance ne doit lui être attribuée (`commit_sha_verified=false`).
- **Réseau** : URI MLflow HTTP loopback uniquement (`127.0.0.1`/`localhost`, port explicite). Toute autre destination est refusée.
- **Entrée bornée** : fichier régulier non-symlink, 32 Mio max, 1 Mio par ligne, 50 000 événements max. JSON invalide, forme non-objet ou flux vide = refus.

## Catégories comptées (indicatives, pas qualité)

| Compteur | Exemples de `type` |
|---|---|
| `content_events` | `text`, `reasoning`, `message`, `message.part.updated` |
| `tool_events` | `tool_use`, `tool_call`, `tool_result`, `tool.*` |
| `error_events` | `error`, `*.error` |
| `step_events` | `step*` |
| `other_events` | types inconnus / autres |

## Utilisation (checkout isolé, données non sensibles)

```bash
umask 077
opencode run --format json "Analyse statique consultative de ce checkout de test" > /tmp/opencode-observation.jsonl
SHA="$(git rev-parse HEAD)"
python3 -m scripts.mlflow_opencode_bridge --sha "$SHA" --pr 218 --input /tmp/opencode-observation.jsonl
# Après vérification du serveur MLflow privé loopback:
ARVOR_MLFLOW_TRACKING_URI=http://127.0.0.1:5000 \
  python3 -m scripts.mlflow_opencode_bridge --sha "$SHA" --pr 218 --input /tmp/opencode-observation.jsonl --execute
```

Le JSONL brut peut contenir des données sensibles; ne jamais le committer, l'attacher à une PR, ou le publier. Supprimer selon la politique locale après contrôle.

## Tests

```bash
python3 -m unittest tests.test_mlflow_opencode_bridge -v
```

Les tests sont offline (pas de MLflow, pas d'OpenCode réel). Ils valident parsing, non-divulgation, limites, loopback-only, fail-open, et absence de branchement CI/superviseur/livraison.
