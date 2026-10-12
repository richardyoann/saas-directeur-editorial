# Pilotage privé — Directeur éditorial IA

Référence : richardyoann/saas-directeur-editorial, ID 1411435489.
Project privé : https://github.com/users/richardyoann/projects/3.
56 issues : 8 Epics, 16 Stories, 16 tâches, 16 sous-tâches ; 48 relations natives.
Roadmap proposée à affiner à partir du code WSL, sans inventer l’avancement.

## Fonctionnement du PO

Le heartbeat « PO — Directeur éditorial IA » vérifie toutes les quatre heures
les PR, CI, risques et nouvelles preuves. Rester silencieux si l’état n’a pas
changé. L’enregistrement du calendrier ne prouve pas une exécution planifiée.
La définition `product_owner.toml` peut être lue explicitement par Codex CLI;
aucune découverte native de cet agent n’est annoncée.

`python -m pilotage.po --sha <commit inspecté>` calcule uniquement les critères
des stories, pour ne pas doubler les critères repris par les sous-tâches.
`evidence.json` est initialement vide. Ajouter des preuves revues contenant
`result`, `commit`, `criteria`, `reviewer`, `url`, `mode` et `at` (date timezone).
Le champ `verified` du critère et son ID de preuve doivent être renseignés
après revue; une URL et une CI verte seules ne suffisent pas.
Pour un critère `requires_real`, les modes automated/simulated sont refusés.
Si le commit change, la preuve devient périmée jusqu’à revue et revalidation.
0 acceptation validée ne signifie pas 0 code développé : la baseline historique
doit être reconstituée avec la version exacte testée.

Todo : prévu/à revalider. In Progress : travail engagé. Blocked : obstacle
identifié. Done : critères tous vérifiés, dépendances acceptées et revue PO.
Les workflows auto-close, item closed → Done et PR merged → Done sont désactivés.
Le champ « Sub-issues progress » représente les fermetures, pas les acceptations.

## Conventions et PR

Branches : `feat/ID-description`, `fix/ID-description`, `ops/ID-description`.
Commits : `type(ID): résumé`. PR : IDs, critères, preuve au SHA, risques,
migrations et retour arrière. Utiliser Refs plutôt que Closes tant que les
critères ne sont pas tous acceptés. Aucune fusion automatique.

Le workflow CI utilise un runner GitHub Ubuntu et une base PostgreSQL de service
isolée; aucun runner privé hébergeant Qwen n’est ajouté. Tests modèle simulés
distingués des essais Qwen réels. Permissions contents:read, pas de secrets
dans les jobs de PR, actions officielles figées par SHA. Exécuter aussi les tests
historiques Linux et corriger les échecs avant revue. Main non protégé à
l’inspection; protection et disponibilité selon plan doivent être vérifiées.

## Audit métier transactionnel

`audit.mutate` applique CRUD versionné aux cinq types prompt/treatment/scenario/
scene/result. L’appelant détient la transaction : mutation, audit et outbox
sont validés ensemble. IDs tenant/acteur/corrélation opaques, source UUID unique,
verrouillage de version et clés d’idempotence. La suppression est logique;
le contenu est vidé, la preuve d’audit est conservée. Une API doit dériver tenant
et acteur d’une authentification réelle, jamais des champs libres d’une requête.
Ce composant est une bibliothèque; son raccordement aux futures routes métier
reste à faire et n’est pas annoncé actif sur la production.

`migration.sql` est révisable : ne l’appliquer qu’à une cible explicitement
autorisée. `po_audit` est append-only, mais un administrateur DB peut toujours
changer la politique; aucune garantie contre cet administrateur n’est annoncée.
La séparation des rôles DB et des autorisations API reste à configurer.

`notify.once` vérifie auth.test pour T0C7ZUAM4DR, alloue un lot durable et envoie
à C0C883XR3DF seulement des compteurs kind/operation et UUID de lot.
Au maximum un lot de 100 événements par minute, vieillissement de 60 secondes,
8 tentatives, backoff et Retry-After. Envoi incertain : pas de retry automatique.
Réconciliation manuelle obligatoire par preuve Slack avant modification de
l’état. Aucun contenu/titre métier, token ou erreur brute dans le digest.
Ce worker nécessite PO_DATABASE_URL et TRACE_SLACK_BOT_TOKEN fournis au
processus via stockage de secrets, jamais dans le chat/Git. Le connecteur Slack
de Codex est une authentification distincte. Aucun daemon installé implicitement.

## Intégration du POC et reprise

PR #1 : audit/outbox des work items, webhook PR signé et audit génération opt-in.
Elle est brouillon, head 67b1a52e63fa6b8423dc32f0c8afa75a432ccf79 à l’inspection.
Préserver ses modifications et celles de WSL. La bibliothèque métier du
pilotage ne remplace pas son schéma trace_* ; intégrer après revue des deux PR.
À terme, tous les endpoints métier doivent passer par la transaction auditée.
Notifications PR/CI : le PO lit les événements GitHub et publie une synthèse
dédupliquée. Le webhook temps réel du POC demande encore endpoint et secret
runtime; aucun webhook distant opérationnel n’est annoncé.

WSL ne démarre pas dans cette session : disque Ubuntu introuvable. Ne pas
réinitialiser/réinstaller la distribution; localiser la sauvegarde avec
l’utilisateur avant restauration. Source Windows préservée et non traitée
comme preuve de l’état actuel de WSL.

## Droits et limites

Connecteur GitHub : accès admin/push/pull au dépôt confirmé; outils Issues/PR,
pas de méthode Projects ni quota/headers exposés. UI propriétaire authentifiée
utilisée pour le Project; visibilité privée vérifiée. Aucun quota chiffré
inventé. Écritures séquentielles, reprises par IDs, arrêt en cas d’erreur de
permission ou de rate limit. La CLI WSL n’a pas pu vérifier rate_limit.
Slack List : deux entrées lues, aucun transfert de clôture inventé. L’ancien
refus de modification de List n’empêche pas le centre GitHub; la List reste
historique, sans suppression. Bot worker, secrets Actions et accès endpoint
restent à vérifier individuellement.

Documentation officielle :
- https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues
- https://docs.github.com/en/actions/reference/security/secure-use
- https://developers.openai.com/blog/automating-repetitive-work-at-openai-with-codex

## État actualisé au 12 octobre 2026

Les constats de disque WSL inaccessible et de runner privé absent ci-dessus sont historiques. Ubuntu 26.04 est accessible; un runner privé a livré main avec succès. Voir docs/AUTONOMOUS_DELIVERY.md pour les preuves, prérequis, reprise et consigne de documentation continue. Ubuntu 24.04 est exclue.
