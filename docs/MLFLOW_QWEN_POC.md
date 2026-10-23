# POC isolé MLflow / Qwen — Arvor

**Statut : code expérimental, non installé sur le PC et non relié au runtime Arvor.**
Aucune migration, aucun changement de Compose, de service systemd, de secret, de volume, de release ou de workflow de livraison.

## Objectif et critères d'acceptation

Comparer les mesures d'un appel réel à Qwen/llama.cpp dans MLflow avec un prompt **synthétique** sans exporter de données métier :

- Un run et une trace LLM dans l'expérience arvor-qwen-local-poc.
- Hash SHA-256 du prompt, identité du modèle filtrée, durée, statut, finish_reason, longueur de sortie, compteurs tokens disponibles.
- Aucun prompt/réponse brute, jeton, tenant, acteur, IP ou URL fournisseur dans les traces.
- La commande sans --execute ne lance pas de génération.
- Une seule génération explicite, sans retry automatique.
- Pas d'effet sur les tables PostgreSQL métier, l'audit/outbox, les images, MinIO et la CI principale.

Ce POC ne réalise **pas** encore d'évaluation éditoriale, de mesure de qualité visuelle, ni d'instrumentation automatique du service API/worker. MLflow reste un outil d'observabilité expérimental.

## Prérequis

- Checkout Arvor séparé de la release active sur WSL.
- Qwen accessible à une adresse HTTP privée connue par le PC (la passerelle WSL peut changer).
- Python 3.12 et accès temporaire au registre Python pour créer un **venv indépendant**.
- Environnement MLflow destiné à la démonstration, jamais accessible publiquement.

La liste des dépendances est séparée dans requirements-mlflow-poc.txt. Ne pas modifier le venv qui sert la production. L'installation locale doit être explicitement validée par l'opérateur du PC.

## Exécution MANUELLE après autorisation d'installation

Exemple de chemins pour le PC de développement ; adapter si le dossier n'existe plus. Cette procédure n'a pas été exécutée par le changement Git :

~~~bash
mkdir -p /home/yoann_admin/experiments/mlflow-poc
python3.12 -m venv /home/yoann_admin/experiments/mlflow-poc/.venv
/home/yoann_admin/experiments/mlflow-poc/.venv/bin/python -m pip install -r requirements-mlflow-poc.txt
~~~

Dans un premier terminal, démarrer uniquement en loopback :

~~~bash
/home/yoann_admin/experiments/mlflow-poc/.venv/bin/mlflow server \
  --host 127.0.0.1 --port 5000 \
  --backend-store-uri sqlite:////home/yoann_admin/experiments/mlflow-poc/mlflow.sqlite \
  --default-artifact-root /home/yoann_admin/experiments/mlflow-poc/artifacts
~~~

Dans un second terminal depuis le checkout du dépôt, en adaptant l'IP Qwen :

~~~bash
LLM_BASE_URL=http://172.31.48.1:8081 \
  /home/yoann_admin/experiments/mlflow-poc/.venv/bin/python -m scripts.poc_mlflow_qwen

# Seulement après contrôle du serveur et décision de lancer UNE génération :
LLM_BASE_URL=http://172.31.48.1:8081 \
  /home/yoann_admin/experiments/mlflow-poc/.venv/bin/python -m scripts.poc_mlflow_qwen --execute
~~~

L'UI MLflow est alors consultable uniquement sur http://127.0.0.1:5000.
Le tracking URI est http://127.0.0.1:5000 par défaut ; ARVOR_MLFLOW_TRACKING_URI peut pointer vers une autre adresse de **loopback HTTP**. Le script refuse un serveur de suivi distant/public et une URL fournisseur publique. Aucune clé de serveur n'est nécessaire pour la démonstration locale.

## Tests non destructifs

~~~bash
/home/yoann_admin/experiments/mlflow-poc/.venv/bin/python -m unittest discover -s tests -p 'test_mlflow_poc.py' -v
~~~

Les tests unitaires valident le garde d'exécution, le refus des URL publiques et la non-divulgation des contenus dans les métadonnées. Ils ne prouvent pas la connexion MLflow/Qwen sur le PC. Pour conclure, constater un vrai run avec une trace sur l'instance privée et vérifier l'absence de contenu sensible.

## Sécurité et exploitation

- Ne jamais activer mlflow.openai.autolog pour cette expérimentation : la capture automatique peut enregistrer prompt et sortie.
- Ne pas publier les traces ou la base SQLite dans GitHub, Slack ou un rapport.
- En cas d'échec fournisseur, seul un code générique est journalisé ; aucun rejeu n'est déclenché.
- La base SQLite d'essai et les artefacts restent dans le dossier expérimental, sans connexion aux volumes Arvor. La persistance PostgreSQL/MinIO sera un **autre lot**, après preuve d'utilité.
- Aucun composant de production ne dépend de MLflow. Une panne ou une absence du serveur d'essai ne perturbe pas Arvor.
- La fusion éventuelle ne constitue pas une autorisation de livraison PC. Les règles AGENTS.md et le SHA approuvé s'appliquent toujours.

## Décision de poursuite

Poursuivre uniquement si le POC donne un run réel reproductible, sans fuite de contenu, et si la durée/tokens/erreurs identifient un problème exploitable. Ensuite tester un jeu de scènes synthétiques et une grille d'évaluation éditoriale, sans brancher de porte bloquante sur la CI tant que le juge n'est pas étalonné humainement.
