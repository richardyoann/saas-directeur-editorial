# OpenCode → MLflow : observabilité indépendante

Ce connecteur expérimental complète la PR #218 sans modifier la CI locale de la PR #215 ni ses 16 gates. MLflow ne signe aucune preuve, ne publie aucun statut GitHub et n'autorise aucune fusion ou livraison.

## Contrat

L'entrée est le JSONL de `opencode run --format json`. Seuls les compteurs d'événements et le SHA exact sont conservés. Les messages, prompts, outils, arguments, résultats, identifiants de session, journaux de CI et secrets ne sont jamais envoyés à MLflow. Les types d'événements inconnus sont comptés comme `other_events` ; ces catégories sont indicatives, **pas** des mesures de qualité. L'entrée est limitée à 32 Mio, 1 Mio par ligne et 50 000 événements.

## Utilisation dans un checkout de test isolé

Préparer un serveur MLflow privé sur `127.0.0.1:5000` selon `docs/MLFLOW_QWEN_POC.md`. Utiliser le venv expérimental distinct, jamais le venv de l'API Arvor. Exemple avec une commande OpenCode explicitement autorisée, sur une copie de test et sans secrets :

```bash
umask 077
opencode run --format json "Analyse statique consultative de ce checkout de test" > /tmp/opencode-observation.jsonl
SHA="$(git rev-parse HEAD)"
python -m scripts.mlflow_opencode_bridge --sha "$SHA" --pr 218 --input /tmp/opencode-observation.jsonl
# Après vérification du serveur privé :
python -m scripts.mlflow_opencode_bridge --sha "$SHA" --pr 218 --input /tmp/opencode-observation.jsonl --execute
```

L'exemple ne doit pas être lancé sur un checkout contenant des données privées non autorisées : le JSONL brut local peut contenir prompts et réponses. Supprimer le fichier brut selon la politique locale de conservation, après les contrôles nécessaires. Ne jamais l'ajouter au dépôt ni à une attestation. Ne pas considérer le code retour de ce connecteur comme un résultat de test ou de revue : une panne MLflow est signalée `telemetry_unavailable`, sans effet sur le verdict de CI.

## Limites et acceptation

Les tests `python -m unittest tests.test_mlflow_opencode_bridge -v` sont indépendants du serveur MLflow et du moteur OpenCode. Ils vérifient les filtres et les erreurs, pas une intégration réelle. Avant activation sur WSL : vérifier les formats JSONL réels, la présence de MLflow en loopback, la confidentialité des traces, et la séparation du superviseur de confiance et des preuves de la PR #215. Ne pas faire de ce connecteur une 17e gate. Aucun branchement automatique, aucune fusion, aucune livraison PC dans cette PR.
