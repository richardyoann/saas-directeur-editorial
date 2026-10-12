# Livraison privée guidée par les tests

Autorisation permanente du 12 octobre 2026 : diagnostic, développement,
corrections, tests, revue, documentation, PR et fusion validée peuvent avancer
sans demande de Go à chaque étape. **La MEP nécessite la validation humaine
explicite du SHA exact**, y compris une activation sur le PC privé.
Cette règle remplace l'autorisation d'installation automatique du 11 octobre.
La validation des résultats éditoriaux reste humaine.

## Validation et activation d'une MEP

LOCAL_PC_ENABLED=false bloque le déclenchement automatique de livraison après
la CI de main. Le service déjà actif reste en place. Préparer les changements,
les preuves CI et de revue sur le SHA exact, les risques et le retour arrière,
puis présenter ce dossier à l'utilisateur pour validation.

Après accord explicite seulement : vérifier que main correspond toujours au
SHA approuvé et que sa CI a réussi ; suspendre toute autre fusion pendant la
fenêtre de livraison ; activer temporairement LOCAL_PC_ENABLED et relancer
la livraison du run correspondant à ce SHA. Vérifier la release active et sa
preuve réelle, puis remettre LOCAL_PC_ENABLED=false même en cas d'échec.
Si main a changé, demander une validation du nouveau candidat. Aucun script
de préparation ni suivi planifié ne peut donner cette validation à sa place.
Le workflow existant prépare et active dans la même exécution : ne pas le
déclencher avant l'accord MEP. Les travaux indépendants peuvent continuer.

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
La livraison PC peut se déclencher après CI réussie d'un push main, uniquement
après validation MEP et activation temporaire, jamais depuis une PR non fusionnée. L'automatisation ChatGPT événementielle assure revue,
correction et suivi ; sa création ne prouve pas son premier déclenchement.

## Raccordement unique du PC

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
LOCAL_RELEASE_ROOT, LOCAL_CONFIG_PATH, et garder LOCAL_PC_ENABLED=false ;
passer temporairement à true uniquement après validation MEP et des prérequis. La configuration privée doit aussi fournir
PO_DATABASE_URL, EDITORIAL_API_TOKEN (32 caractères minimum),
EDITORIAL_TENANT_ID et EDITORIAL_ACTOR_ID en plus de LLM_BASE_URL. Aucun de ces
secrets ne doit être copié dans GitHub, Slack ou les journaux. Une seule
installation initiale du runner et du service est nécessaire ; chaque nouvelle
activation reste soumise à validation MEP.

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
Le contrôle réel de main 3313e82c, le 12 octobre 2026, a confirmé finish_reason=stop
et le parcours éditorial complet. Une réponse sans ce champ reste bloquante.

## Provenance de la release privée

Les nouveaux traitements exécutés depuis une release immutable utilisent le SHA
du répertoire de release vérifié par deploy_local et le PID systemd, même si
EDITORIAL_CODE_VERSION dans la configuration privée est périmé. En checkout de
développement, la variable reste utilisée. Aucune trace existante n'est réécrite.

## État du raccordement — 12 octobre 2026

Ubuntu 26.04 exclusivement. Runner officiel 2.338.0, archive vérifiée par
SHA-256, enregistré editorial-pc-ubuntu2604 et observé online. Service utilisateur
editorial-actions-runner.service avec redémarrage automatique et linger actif.
Tâche Windows « Codex - Editorial Ubuntu 26.04 » au logon, exécutée sans fenêtre,
maintenant WSL actif. Le PC doit rester allumé et éveillé; la tâche ne modifie
pas les réglages de veille et ne démarre pas Qwen à sa place.

LOCAL_RELEASE_ROOT=/home/yoann_admin/editorial-runtime;
LOCAL_CONFIG_PATH=/home/yoann_admin/editorial-runtime/private/runtime.env.
Fichier privé existant conservé en 0600. Aucun secret dans les variables GitHub.
Activation LOCAL_PC_ENABLED réservée après contrôles. Job privé uniquement après
Full regression réussie sur push main; les PR non fusionnées ne sont pas déployées.
Release 3313e82c installée via la procédure le 12 octobre: 106 tests sans skip,
API/Qwen/éditorial/persistance/historique/idempotence réels validés, service actif,
reçu last_delivery.json. Aucune migration métier. Le premier job automatique a depuis été vérifié avec succès; voir la preuve datée ci-dessous.

## Mise à jour continue

Consigne utilisateur : à chaque changement, compléter dans la même PR la documentation concernée et les fichiers d’installation/déploiement dont le comportement change (scripts, workflows, modèles de configuration). Garder prérequis, commandes, configuration et reprise cohérents avec le projet réel. Consigner date, SHA vérifié, résultats, limites et blocages; distinguer préparation, CI, installation active et acceptation métier. Ne jamais versionner les secrets. Ubuntu 26.04 exclusivement; Ubuntu 24.04 est exclue.

## Livraison automatique vérifiée — 12 octobre 2026

LOCAL_PC_ENABLED=true depuis 08:47:05 UTC. La première tentative ignorée à 08:00:00 UTC précédait cette activation. La relance s’est terminée avec succès à 09:17:22 UTC :
https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38220920773

SHA installé : cf273496324e6cf971d53b76dadc2c34f7ce5c01 (PR #65 fusionnée). 108 tests réussis sans skip, contrôles API candidate et installée réussis, parcours éditorial réel validé. Analyse et storyboard : finish_reason=stop, schémas valides, aucune erreur. Répertoire du PID systemd et provenance du traitement conformes au SHA. Reçu last_delivery.json : regression/candidate_live/installed_live/real_editorial_workflow=passed, database_migration=none. Le traitement reste waiting_validation : acceptation éditoriale humaine distincte.

## Contrôles et reprise

Le service ~/.config/systemd/user/editorial-actions-runner.service lance ~/.local/share/editorial-actions-runner/run.sh avec Restart=always, RestartSec=10, TimeoutStopSec=300, KillSignal=SIGTERM. Linger est activé pour yoann_admin. Dépendances système ajoutées : libicu78 et liblttng-ust1t64.

Dans Ubuntu 26.04 :

~~~bash
systemctl --user is-active editorial-actions-runner.service editorial-api.service
loginctl show-user yoann_admin --property=Linger
readlink -f /home/yoann_admin/editorial-runtime/current
cat /home/yoann_admin/editorial-runtime/last_delivery.json
gh run view 38220920773 --repo richardyoann/saas-directeur-editorial
~~~

Comparer le SHA du reçu, current et le répertoire réel du PID de l’API. Remplacer l’ID du run pour toute nouvelle livraison; une preuve historique ne certifie pas le nouveau SHA. La tâche Windows maintient WSL après ouverture de session; elle ne démarre pas Qwen et ne maintient pas le PC éveillé. Vérifier la disponibilité du modèle avant les contrôles réels.

Pour un job ignoré avant activation, vérifier ses conditions et le SHA courant de main avant de relancer :

~~~bash
gh run rerun <ID> --repo richardyoann/saas-directeur-editorial
~~~

Sur incident, consulter les journaux sans secrets ni contenu métier, préserver releases et base métier. deploy_local gère le retour au code précédent après échec de la bascule, selon les limites ci-dessus. Tenir scripts/deploy_local.py, scripts/live_api_check.py et .github/workflows/local-delivery.yml cohérents avec les instructions lorsque leur comportement change.

## Economie de contexte Codex

Voir docs/TOKEN_ECONOMY.md : profils .codex/agents, deux sous-agents maximum, contexte minimal et mesures comparables. Aucune modification du runner ni des controles de livraison.

## Installation des routes de décision humaine

L'incrément EDIT-001 ajoute les routes review/reviews au code API; aucune nouvelle variable privée, dépendance ou migration. Le workflow et deploy_local appliquent les mêmes contrôles. Les nouveaux tests utilisent seulement PostgreSQL jetable; les traitements de preuve de livraison restent waiting_validation, sans acceptation humaine automatique. Contrat : docs/EDITORIAL_WORKFLOW.md. Une vérification HTTP déployée vérifie401/404/422 sans modifier de résultat métier.
