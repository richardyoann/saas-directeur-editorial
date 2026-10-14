# INC-2026-10-14 — Remise en service du Directeur éditorial (PC privé)

> **Statut :** résolu pour l'API, PostgreSQL, Qwen et la livraison Studio ; recette UX humaine complète et résilience au redémarrage encore à qualifier.
> **Fenêtre :** 14–15 octobre 2026 (heure de France ; GitHub horodate les exécutions en UTC).
> **Environnement :** Windows 11 → WSL Ubuntu 26.04 → Docker PostgreSQL 16 / Redis / FastAPI systemd utilisateur ; Qwen 2.5 3B Instruct GGUF Q4_K_M dans llama.cpp sous Windows, backend Vulkan AMD Radeon RX 580 8 Go.
> **Référence de livraison :** `07f99edbec1374af6a929aa814169d32efa6ef3a`.
> **Confidentialité :** aucune valeur de `.env`, mot de passe, jeton, contenu de prompt ou sortie métier n'est reproduite ici.

## 1. Impact et synthèse

- **Impact utilisateur observé :** interface `http://localhost:8000/studio` indisponible (404), génération éditoriale non utilisable tant que PostgreSQL/Qwen étaient hors ligne. Les routes `/health` ont ensuite répondu 200, ce qui pouvait donner une impression trompeuse de rétablissement.
- **Impacts sur les données :** aucun effacement observé. Le volume existant `saas-directeur-editorial_postgres_data` a été conservé ; après redémarrage PostgreSQL a terminé une récupération WAL et les requêtes applicatives `SELECT 1` ont réussi. Cela **ne prouve pas**, à lui seul, l'intégrité exhaustive des données.
- **Résolution :** localisation du véritable dépôt Git, redémarrage FastAPI et PostgreSQL, relance de llama.cpp/Vulkan et validation d'une génération Qwen réelle depuis WSL, ajout d'un mot de passe Studio distinct, sauvegarde `pg_dump -Fc` vérifiée par `pg_restore -l`, livraison PC du SHA validé avec tests avant/après activation.
- **Preuve forte :** [Private PC delivery #38653094752](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38653094752) = `success` ; reçu de déploiement présent dans les logs : `candidate_live=passed`, `installed_live=passed`, `real_editorial_workflow=passed`, `regression=passed`, `database_migration=none`.
- **Qualification de couverture :** 155 tests Python/PostgreSQL sans erreur/skip sur le runner PC ; 10 parcours Chromium sur **fixture/API simulée**, exécutés lors d'une CI dédiée d'un SHA antérieur ([workflow #38633385180](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38633385180), relancé avec succès). Cela ne prouve pas que tous les parcours sont acceptés dans le navigateur réel du PC.

## 2. Chronologie des symptômes, actions et résultats

| ID | Symptôme/observation (preuve) | Diagnostic retenu | Action effective et résultat | Certitude |
| --- | --- | --- | --- | --- |
| INC-01 | `fatal: not a git repository` dans `~/saas-directeur-editorial`. | Le répertoire de travail ne contient pas de `.git` ; vrai checkout à `~/saas-directeur-editorial-github/.git`. | `find /home -maxdepth 5 -name .git`, puis `git -C ...-github fetch origin` et `git rev-parse origin/main`. | **Confirmé** par liste des dossiers et `git fetch`. |
| INC-02 | `CategoryInfo / NativeCommandError`, syntaxe `Test-Path` ou `Get-NetTCPConnection: command not found`. | Mélange entre PowerShell Windows et Bash WSL ; parfois erreurs natives surfacées en rouge malgré une sortie utile. | Étiqueter explicitement chaque terminal ; utiliser `wsl -d Ubuntu-26.04 -e <commande Linux>` depuis PowerShell, ou ouvrir PowerShell séparément pour les cmdlets Windows. | **Confirmé** par prompts `PS C:\...` vs `yoann_admin@...$`. |
| INC-03 | `editorial-api.service` `inactive (dead)`, désactivé au démarrage ; journaux montrant `Application shutdown complete`. | Service arrêté proprement ; **cause initiale de l'arrêt non démontrée**. | `systemctl --user start editorial-api.service` ; après initialisation Uvicorn, `GET /health` = 200. Premier `curl` trop rapide = connexion refusée. | Service rétabli **confirmé** ; cause d'arrêt **inconnue**. |
| INC-04 | `/studio` et `/ready` renvoient 404, alors que `/health` = 200. | Release active obsolète `a032a37f…`; routes absentes dans celle-ci. La panne n'était pas uniquement un problème de réseau ni de mot de passe. | Contrôle `current`, `last_delivery.json`, comparaison au SHA GitHub et qualification du bon chemin de release. Livraison effectuée plus tard. | **Confirmé** par réponses HTTP et diagnostic `expected_sha_matches=false`. |
| INC-05 | `readlink` initialement mal saisi / sans sortie utile, suspicion de lien cassé. | Erreur de commande/syntaxe ; pas de preuve de lien cassé. | `ls -ld ~/editorial-runtime/current`, `readlink ...`, `realpath -e ...` : symlink valide vers la release `a032a37f…` ; anciennes releases conservées. | **Confirmé** : lien valide. |
| INC-06 | `EDITORIAL_WEB_PASSWORD : ABSENT`, première saisie rejetée : « Minimum 32 caractères ». | Secret web requis par la nouvelle interface et par la garde de livraison ; distinct du jeton API. | Identifié `~/editorial-runtime/current/.env` → `~/editorial-runtime/private/runtime.env`; sauvegarde de configuration puis secret défini sans écho ; vérification `Studio : OK`. | **Confirmé** ; aucune valeur conservée dans cette note. |
| INC-07 | `psycopg.OperationalError`, sans SQLSTATE ; `ConnectionRefusedError` en TCP. | Conteneur `editorial-postgres` arrêté, port local non disponible (autres services Docker sans lien direct). | `docker start editorial-postgres`, attente `pg_isready` ; logs montrent récupération après arrêt incorrect, puis `ready to accept connections`. Test `psycopg.connect(...).execute('SELECT 1')` = OK. | **Confirmé** ; origine de l'arrêt Docker **non prouvée**. |
| INC-08 | `Qwen /health` et `/v1/models` en `ConnectTimeout` depuis WSL, port Windows 8081 sans écoute. | Serveur `llama-server` non démarré ; le backend Vulkan **n'est pas lui-même un serveur**. | Recherche de `llama-server.exe`, `ggml-vulkan.dll`, `--list-devices` : AMD RX 580 reconnue ; relance de llama.cpp + Qwen sur l'adresse Windows accessible depuis WSL. `/v1/models`, `/health` et `/v1/chat/completions` ont répondu. | **Confirmé** ; permanence de l'adresse Windows **non garantie**. |
| INC-09 | Deux premiers `pg_dump -Fc` : `fe_sendauth: no password supplied` ; un essai avec `POSTGRES_PASSWORD` également rejeté. | `pg_dump` ne recevait pas le mot de passe valide ; la variable Docker supposée ne suffisait pas. **Pas une preuve de corruption ni de mot de passe incorrect.** | Extraction en mémoire du mot de passe déjà utilisé par `PO_DATABASE_URL` ; transmission au processus conteneur via entrée standard, sans l'afficher ; `pg_dump` réussi, taille rapportée ~26,7 Ko, `pg_restore -l` réussi. | **Confirmé** pour création et lisibilité ; **restauration complète non testée**. |
| INC-10 | `Private PC delivery` = `skipped` malgré `Full regression` verte. | Garde `LOCAL_PC_ENABLED` désactivée avant validation humaine ; `workflow_run` doit venir de `push main` après CI réussie. | Accord explicite sur SHA puis activation temporaire de `LOCAL_PC_ENABLED=true`. | **Confirmé** par YAML et exécutions. |
| INC-11 | Relance répétée de l'ancien run `#38636002145` : `skipped` puis `startup_failure` sans job affecté, alors que runner `editorial-pc-ubuntu2604` = Online/Idle. | **Cause exacte du `startup_failure` non établie** ; runner indisponible écarté sur capture. Réutiliser cet ancien événement ne débloquait pas la livraison. | Relance du job **Full regression** `#38635895291` sur le **même SHA**, succès ; nouvel événement `workflow_run` engendrant `Private PC delivery #38653094752`. | Nouveau déclenchement et succès **confirmés** ; cause GitHub racine **à investiguer si récurrence**. |
| INC-12 | Release installée non encore qualifiée avant le job. | Nécessité de distinguer CI, candidate et version réellement active. | Job `install-and-live` sur runner PC : base test jetable, 155 tests réussis, HTTP API/Studio, vraie génération Qwen, workflow métier, persistance, historique, idempotence, vérification de la release active ; succès final. | **Confirmé** par logs de livraison. |

**Corrections de code indépendantes et pertinentes :** la PR [#79](https://github.com/richardyoann/saas-directeur-editorial/pull/79) a ajouté un refus HTTP 503 lorsque le mode asynchrone est activé **sans worker enregistré**, un contrôle de disponibilité du worker en mode async, et le diagnostic de release `scripts/diagnose_runtime.py`. Ces modifications ont été fusionnées dans le SHA livré ; elles n'expliquent pas l'arrêt initial des services Windows/Docker.

## 3. Causes : distinction nécessaire

### Causes confirmées à l'instant de l'incident
1. Dossier Git incorrect pour les commandes `git` ;
2. Service FastAPI arrêté, puis release ancienne dépourvue des routes Studio/readiness ;
3. Conteneur PostgreSQL arrêté ;
4. Serveur Qwen/llama.cpp arrêté sous Windows, port 8081 sans listener ;
5. Secret Studio initialement non configuré ;
6. Commande `pg_dump` sans secret transmis ;
7. Garde GitHub empêchant les anciens événements d'être déployés.

### Origines non démontrées (ne pas écrire « cause racine certaine »)
- Pourquoi FastAPI et le conteneur PostgreSQL avaient été arrêtés (veille, redémarrage, arrêt volontaire, dépendance Docker, autre) ;
- Pourquoi `POSTGRES_PASSWORD` n'a pas fourni l'authentification attendue ;
- Pourquoi GitHub a qualifié la troisième tentative de l'ancien événement de `startup_failure` ;
- Si le serveur llama.cpp ou WSL restera disponible après veille/reboot ;
- Si la sauvegarde de 26,7 Ko est restaurable dans une base vide ;
- Si les usages UI réels (revue, révision, mobile, publication) satisfont toutes les attentes métier.

## 4. Preuves et traçabilité (reproductibles)

- **CI main approuvée :** [Full regression #38635895291](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38635895291), relance même SHA réussie.
- **Run sans livraison :** [Private PC delivery #38636002145](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38636002145), tentatives `skipped` / `startup_failure` ; ne pas réinterpréter en tests applicatifs échoués.
- **Livraison effective PC :** [Private PC delivery #38653094752](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38653094752) et `last_delivery.json`. Logs : 155 tests / 0 échec / 0 erreur / 0 skip, `candidate_live=passed`, `installed_live=passed`, `real_editorial_workflow=passed`.
- **Parcours navigateur automatisés :** [Studio browser journeys #38633385180](https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38633385180), 10/10 tests Chromium réussis sur API simulée ; **autre SHA**, pas la recette live sur PC.
- **Logs et captures conversationnelles :** evidence du `/health=200` + `/studio=404`, `pg_isready`, `SELECT 1`, `/v1/models`, `/health`, génération « Arvor Studio opérationnel. », réussite de `pg_restore -l`. Pas de reproduction de captures contenant des informations privées dans Git.

## 5. Mesures préventives MCO, par priorité

| Priorité | Mesure | Signal/action et critère de fermeture |
| --- | --- | --- |
| P0 | **Fermer la fenêtre de déploiement** | Vérifier manuellement `LOCAL_PC_ENABLED=false` après livraison, même si GitHub a réussi. La valeur post-incident **n'est pas vérifiable depuis la connexion actuelle**. |
| P0 | **Tester une restauration PostgreSQL isolée** | `pg_restore` complet dans une base jetable, validation schéma/volumétrie cohérente ; ne jamais restaurer dans la base de production pour ce test. |
| P0 | **Contrôle de release actif** | SHA de `current` = SHA de `last_delivery.json` = SHA accepté ; vérifier PID du service, `/health`, `/ready`, `/studio`. |
| P1 | **Démarrage dépendances après reboot** | Documenter/superviser le démarrage de Docker PostgreSQL, llama.cpp/Vulkan et systemd utilisateur ; vérifier plutôt que supposer qu'un service `disabled` redémarre. |
| P1 | **Alerte dépendances** | Surveiller `/health` vs `/ready`, disponibilité `LLM_BASE_URL/health`, `pg_isready`, âge des runs et échecs LLM ; ne pas générer de contenus à chaque sonde. |
| P1 | **Documenter l'adresse Windows/WSL** | L'adresse `172.31.48.1` était valide pendant l'incident ; elle peut changer. Tester TCP et HTTP avant de modifier `LLM_BASE_URL` ou le pare-feu. |
| P1 | **Sauvegardes industrialisées** | Authentification issue de la config effective, dump privé et atomique, `pg_restore -l`, rétention/rotation et exercice de restauration ; alerter si dump vide. |
| P1 | **Automatiser le rapport d'incident sans secret** | Capturer heure, SHA, version des services, codes HTTP, classe des erreurs, numéros des runs et actions ; éviter les prompts bruts, jetons, mots de passe. |
| P2 | **Recette utilisateur sur la release installée** | Approuver/rejeter/réviser une histoire réelle, vérifier historique, navigation mobile, persistance après redémarrage, erreurs 401/409/422 et tests d'accès privé. |
| P2 | **Worker asynchrone** | Activer seulement après superviseur et recette spécifique ; par défaut il reste désactivé. Voir `docs/ASYNC_EDITORIAL_WORKER.md`. |

## 6. Actions à ne pas reproduire

- Ne pas assimiler `GET /health=200` à « SaaS prêt » : `/health` ne vérifie pas toutes les dépendances.
- Ne pas lancer `git` dans le dossier de travail sans `.git` ; ne pas utiliser `git init`, `reset --hard` ou recopier `.git` à l'aveugle.
- Ne pas exécuter `Test-Path`/ `Get-NetTCPConnection` dans Bash WSL ni les chemins Windows `C:\...` avec `cd` Linux.
- Ne pas conclure que `readlink` absent prouve un lien cassé après une syntaxe incorrecte.
- Ne pas utiliser `docker compose down -v`, `docker volume prune` ou détruire `editorial-postgres` pour régler un timeout.
- Ne pas confondre mot de passe absent, erroné et service indisponible ; conserver les codes/types d'erreurs **sans afficher leurs chaînes potentiellement sensibles**.
- Ne pas appeler Vulkan un serveur LLM : **llama.cpp sert HTTP**, Vulkan accélère les calculs si son backend et les couches GPU sont réellement engagés.
- Ne pas considérer `pg_restore -l` comme une preuve de restauration complète.
- Ne pas contourner la validation du **SHA exact**, utiliser une CI verte d'un autre commit, ni laisser `LOCAL_PC_ENABLED=true` après livraison.
- Ne pas relancer automatiquement une génération à résultat réseau incertain : utiliser l'idempotence et la réconciliation explicitement prévues.

## 7. Références

- [Guide MCO et arbre de décision](RUNBOOK_DIAGNOSTIC_PC.md)
- [Index MCO, modèle de ticket et classification](README.md)
- [Livraison privée et contraintes](../AUTONOMOUS_DELIVERY.md)
- [Service web privé et tests](../STUDIO_PRIVATE.md)
- [File/worker éditorial, mode async OFF par défaut](../ASYNC_EDITORIAL_WORKER.md)
- [Schéma et historique métier](../EDITORIAL_WORKFLOW.md)
