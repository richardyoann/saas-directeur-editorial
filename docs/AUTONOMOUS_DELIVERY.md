# Livraison privée guidée par les tests

Autorisation utilisateur du 11 octobre 2026 : revue, corrections, fusion validée,
installation privée sur PC et tests réels sans demande de Go à chaque étape.
Le message de succès informe l'utilisateur ; il n'est pas une nouvelle demande
d'autorisation. Publication publique exclue.

## Critères obligatoires

Avant le code : critères d'acceptation, contrats touchés, cas limites, erreurs,
effets de bord sur routes, données, permissions, ressources et configuration.
Créer un test pertinent qui échoue pour le défaut à corriger, puis le corriger.
Conserver tous les tests historiques. `scripts/run_regression.py` exécute tests/
et pilotage/ lorsqu'il existe ; zéro test ou test ignoré bloque la livraison.
Une suppression de test doit être explicitement justifiée et revue, jamais une
méthode pour faire passer la CI. Les échecs préexistants restent des blocages.

Revue du diff ET des appels et contrats affectés sur le SHA exact. Une revue
sur un ancien SHA est périmée après correction. Le compte connecté peut être
l'auteur : consigner une revue COMMENT sans simuler une approbation humaine.
Respecter les protections de branche. Fusion uniquement après revue sans
défaut bloquant et tests requis réussis ; CI PR teste le merge avec main.

Le workflow Full regression teste les PR et main, PostgreSQL 16 jetable compris.
Les migrations de traçabilité sont appliquées uniquement à sa base po_test.
La livraison PC se déclenche après CI réussie d'un push main, jamais à partir
d'une PR non fusionnée. L'automatisation ChatGPT événementielle assure revue,
correction et suivi ; sa création ne prouve pas son premier déclenchement.

## Raccordement unique du PC (pas encore exécuté)

Depuis un accès autorisé au PC, utiliser WSL/Linux et un utilisateur dédié au
projet, Docker accessible, Python 3.12+ avec venv, systemd utilisateur actif.
Enregistrer le runner GitHub du dépôt privé avec label editorial-pc en suivant
Settings → Actions → Runners → New self-hosted runner. Installer son service.
Ne pas afficher ni versionner son token d'enregistrement. Garder PC et WSL actifs.

Choisir un répertoire de releases neuf, distinct du checkout de développement,
par exemple /home/yoann_admin/editorial-runtime. Utiliser une configuration .env
existante validée, à chemin absolu, hors releases et avec permissions privées.
Configurer un service systemd utilisateur nommé editorial-api.service :

```ini
[Unit]
Description=Directeur editorial API privee
After=network.target
[Service]
WorkingDirectory=/home/yoann_admin/editorial-runtime/current
ExecStart=/home/yoann_admin/editorial-runtime/current/.venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
[Install]
WantedBy=default.target
```

Vérifier qu'aucun autre serveur n'occupe le port 8000 avant activation. Adapter
les chemins au compte réel du runner. Charger le service (daemon-reload), sans
démarrer une release inexistante. Configurer les variables GitHub du dépôt :
LOCAL_RELEASE_ROOT, LOCAL_CONFIG_PATH, puis LOCAL_PC_ENABLED=true uniquement
après vérification des prérequis. La configuration privée doit aussi fournir
PO_DATABASE_URL, EDITORIAL_API_TOKEN (32 caractères minimum),
EDITORIAL_TENANT_ID et EDITORIAL_ACTOR_ID en plus de LLM_BASE_URL. Aucun de ces
secrets ne doit être copié dans GitHub, Slack ou les journaux. Une seule
installation initiale du runner et du service est nécessaire ; ensuite les
nouvelles versions sont automatiques.

Le script prépare une nouvelle release immutable, un venv et toutes les suites
avant de relier la configuration réelle. Il démarre une API candidate sur un
port loopback libre, valide HTTP /health, entrée invalide 422 et génération Qwen
réelle. Il bascule ensuite le lien current, redémarre le service et reteste.
En cas d'échec il revient à la release précédente et la reteste. Un échec du
retour arrière reste un blocage ; ne jamais annoncer un rétablissement sans preuve.
Le checkout de travail, les données et les anciennes releases sont conservés.
Aucune migration de la base métier et aucun effacement de volume ne sont faits.

## Limites et preuves

Le contrôle réel valide API, appel modèle et, lorsque les routes éditoriales
existent, le parcours brief → analyse → scénario, l'authentification, le rejeu
idempotent, la persistance et l'historique. Une exécution technique synthétique
par SHA est conservée dans la base privée afin que la preuve soit attribuable;
elle n'est ni publiée ni envoyée à Slack. Le contrôle ne valide pas la qualité
éditoriale, l'identité des poids ni l'interface. Ajouter leurs tests dédiés
avant de les annoncer livrés.
Les changements de schéma exigent un plan sauvegarde/migration/restauration
spécifique ; le retour arrière de code seul ne restaure pas une base migrée.
La version candidate est revérifiée contre le SHA courant de main avant la
bascule ; un ancien run CI terminé tardivement ne doit pas écraser le dernier.
Ne pas déployer automatiquement une migration destructive ou irréversible.

Rapporter SHA, tests exécutés, résultat PC, retour arrière éventuel et limites.
last_delivery.json n'est écrit qu'après succès réel de la version installée.
Ne pas transmettre .env, prompts ou réponse réelle à Slack. Trois tentatives
de correction maximum par incident avant remontée d'un blocage explicite.
Un runner inaccessible, désactivé ou une CI absente n'est jamais un succès.

Références : https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners
et https://docs.github.com/en/actions/reference/security/secure-use


## Renforcement de la revue PR #61

Critères supplémentaires : bloquer une réponse sans finish_reason=stop, vérifier
le PID systemd et son répertoire de release avant de qualifier les tests HTTP,
refuser un checkout suivi modifié, éviter une réinstallation sur événement doublon.
Un reçu de même SHA ne suffit pas : le lien current doit correspondre et les
contrôles du processus et HTTP sont rejoués. Une autre release bloque le succès.
L'API de main ne transmet pas encore finish_reason ; intégrer et revoir la PR #59
avant toute livraison réelle. Aucun succès Qwen n'est déduit de son absence.
