# État du projet

## DEV-005 — workflow éditorial, 11 octobre 2026

- L'utilisateur confirme base complète et LLM connectés, et autorise la progression autonome. Confirmation de son environnement, pas sonde exécutée ici.
- Base du travail : branche ops/OPS-001-pilotage-prive au SHA 0645baf9eb96d23be7eff78de70ddae4c659a77d. Fournisseur de la PR #59 repris explicitement; PR #1/#58/#59 préservées, aucune fusion.
- Nouveau parcours API privé : brief → analyse → scénario/scènes → waiting_validation; deux appels maximum, JSON strict, durée/nombre de scènes vérifiés.
- Identité privée serveur, idempotence par tenant, prompts persistés avant appel, résultats exacts et erreurs archivés, données/audit/outbox atomiques à chaque étape.
- Réutilise uniquement le schéma po_* versionné; aucune nouvelle migration, aucune preuve d'accès aux tables locales non versionnées.
- Local : 60 tests exécutés avec succès, 5 tests PostgreSQL supplémentaires ignorés faute de cible dédiée; 7 tests pilotage exécutés avec succès, 4 PostgreSQL ignorés. Résultat PostgreSQL CI à vérifier séparément.
- Code développé et tests modèle simulés; Qwen réel, interface, reprise durable et activation Slack runtime restent ouverts.
- Guide : docs/EDITORIAL_WORKFLOW.md. La CI est configurée avec une base PostgreSQL 16 dédiée pour les 9 tests concernés, sans modifier la base SaaS.
- DEV-005 reste en cours jusqu'à preuves réelles, revue et acceptation; aucune clôture de critère produit automatique.


## Pilotage — 11 octobre 2026 (prioritaire)

- Dépôt privé confirmé : richardyoann/saas-directeur-editorial, ID 1411435489; main caf1725ad0087fee1a78e078047de6382d210f39 inspecté, droits admin/push/pull.
- Project privé n°3 créé, visibilité private vérifiée, dépôt par défaut correct. 56 issues importées; 48 relations natives vérifiées. Vues backlog hiérarchisé, exécution et PR; priorités/critères/dépendances dans les descriptions.
- Auto-close, item closed → Done et PR merged → Done désactivés et vérifiés. Aucune issue clôturée par cette migration.
- PR #1 brouillon ouvert : POC audit/outbox et webhook signé, head 67b1a52e63fa6b8423dc32f0c8afa75a432ccf79; aucun run Actions associé trouvé. Préserver ce travail. Il est publié sur branche privée, absent de main.
- PO heartbeat créé ACTIVE toutes les quatre heures avec silence sur état inchangé; premier déclenchement planifié non encore testé. Définition CLI livrée; découverte native non testée.
- Bibliothèque métier pilotage.audit et digest développés pour cinq types. 11 tests réussis, dont 4 sur PostgreSQL 16 réel dédié editorial-po-test-20261011 (localhost:55433). Tests HTTP Slack simulés. Base SaaS localhost:5432 inchangée. Aucun hook métier production activé.
- Variables bot/base absentes dans le processus inspecté. Test worker→Slack réel non réalisé. Connecteur Slack distinct; activation runtime ouverte. Aucun webhook distant activé.
- Workflow Actions préparé dans cette PR : tests PO/audit, PostgreSQL isolé et suite historique Linux. Résultat CI à vérifier après publication; ne pas supposer vert.
- WSL : erreur disque Ubuntu introuvable après tentative de lecture hors sandbox. Aucun changement/réinstallation. Docker SaaS PostgreSQL/Redis/MinIO en cours d’exécution observé via docker ps; état Qwen non sondé.
- 48 critères de stories initialement non validés sur la baseline actuelle. Cela ne signifie pas absence de développement; preuves historiques à réattribuer aux versions exactes. Roadmap MVP proposée à affiner.
- Quotas numériques non exposés par le connecteur; pas de chiffre inventé. CLI WSL rate_limit inaccessible. Pas d’erreur rate limit observée sur les écritures réalisées.

Détails : pilotage/GUIDE.md. Aucun merge, migration production, publication publique ou suppression.

## Historique conservé

## Dernière vérification — correction des blocages, 9 octobre 2026

Cette section actualise les constats historiques ci-dessous. Détail et reprise :
`docs/BLOCKERS.md` ; diagnostic relançable : `scripts/diagnose_project.py`.

- Git local accessible via `scripts/git_project.sh` et `.project-git` ; `.git`
  protégé reste inchangé. GitHub CLI installé, authentification enregistrée et
  gestionnaire d’identifiants configuré. Aucun accès distant confirmé : DNS
  GitHub indisponible dans la session. Aucun push ou merge distant.
- Correctif : métadonnées `.project-git` exclues des empreintes et manifestes.
  Sauvegardes et vendor skills exclus des commits ; mémoire privée préservée.
- Sources applicatives, scripts, tests, capacités et documentation désormais
  intégrés à l’index pour un snapshot local complet, sans publication distante.
- Registre externe complété avec le guide Git à la révision fournie : huit
  sources référencées, zéro installation réelle vérifiée.
- Huit skills et huit agents internes validés. Activation toujours refusée
  par les dossiers `.agents`/`.codex` en lecture seule.
- Docker CLI présent ; Compose v2 absent, exécutable Windows non intégré à
  la distribution WSL2 ; accès au socket refusé. Services non vérifiés.
- Appel Qwen actuel depuis la session : HTTP 502 ; la preuve historique
  utilisateur de DEV-001 reste distincte et ne constitue pas une sonde actuelle.
- 53 tests automatisés réussis ; parcours isolé 15/15 et 19 événements vérifiés.
- Aucun changement de réseau, infrastructure, permissions système, migration,
  secret ou `AGENTS.md`. Les restrictions externes ne sont pas annoncées résolues.

## Audit du 9 octobre 2026

- Instructions : `AGENTS.md` lu et préservé ; aucune instruction imbriquée trouvée.
- Git : `.git` est visible mais sans métadonnées exploitables. `git status` et
  `git log` échouent : modifications antérieures et historique non vérifiables.
  Aucun reset, checkout, nettoyage ni suppression effectué.
- Python : `.venv/bin/python` confirme 3.14.4. FastAPI 0.143.0, HTTPX 0.28.1,
  Pydantic 2.14.0, python-dotenv 1.2.4 et Uvicorn 0.54.0 déjà installés.
- API : `apps/api/main.py`, routes `/health` et `/ai/generate`. Frontend,
  workers et workflows encore vides ou au stade de packages placeholders.
- README initialement vide ; aucun manifeste de dépendances ni test initial.
  `ETAT_PROJET.md` absent avant cette intervention.
- Compose : PostgreSQL 16, Redis 7-alpine, MinIO ; ports liés à localhost,
  volumes PostgreSQL et MinIO persistants. Statut réel inconnu : accès au socket
  Docker refusé. Configuration et volumes inchangés.
- `.env.example` : URL d’exemple `http://172.31.48.1:8081`.
  `.env` inchangé ; aucune valeur confidentielle publiée.

## DEV-001 — clôturé pour l’intégration technique

Clôture le 9 octobre 2026 : tests automatisés réussis et preuve de connexion
réelle fournie par l’utilisateur. La qualité éditoriale reste un chantier séparé.

## DEV-001 — développé

- Chargement de `.env` par chemin explicite, priorité aux variables du processus.
- Validation de l’URL HTTP(S), refus des identifiants incorporés.
- Client HTTP injectable, connexion limitée à 5 s et opérations à 120 s.
  `trust_env=False` évite les proxys implicites pour cette connexion locale.
- POST non streaming vers `/v1/chat/completions`.
- Refus des prompts blancs et validation structurée du contenu amont.
- Erreurs : 422 pour saisie invalide, 503 pour configuration invalide,
  502 pour échec HTTP/réseau ou réponse invalide, 504 pour timeout.
- Aucun composant réinstallé ; aucune migration appliquée.

### Fichiers modifiés ou ajoutés

- Modifiés : `apps/api/main.py`, `README.md`.
- Ajoutés : `tests/test_generate.py`, `scripts/check_llm_integration.py`,
  `requirements.txt`, `ETAT_PROJET.md`.
- Préservés : `AGENTS.md`, `.env`, `.env.example`, `compose.yml`, sauvegarde
  `apps/api/main.py.bak` et fichiers préexistants non concernés.

## DEV-001 — testé

Commande : `.venv/bin/python -m unittest discover -s tests -v`.
Résultat final : **6 tests réussis**, avec plusieurs sous-cas : succès et contrat
HTTP, saisie invalide, configuration invalide, connexion impossible/HTTP 503,
connect/read timeout, JSON ou structure/contenu amont invalides.
Les appels amont de ces tests sont simulés. Tests ASGI asynchrones sans ajout de
framework ; une première tentative avec TestClient a été interrompue après
blocage dans cet environnement, puis remplacée par ASGITransport.

Commande réelle : `.venv/bin/python scripts/check_llm_integration.py`.
Le POST traverse FastAPI et le véritable client HTTP, mais retourne **502**.
La sonde réseau confirme la chaîne ConnectError → PermissionError (errno 1).
L’environnement interdit la connexion ; aucun texte Qwen reçu ni inspecté.
Un serveur Uvicorn et le parcours HTTP local complet n’ont pas été validés ici.

### Preuve réelle fournie par l’utilisateur — hors Codex

Test exécuté **par l’utilisateur dans un terminal WSL2 hors de l’environnement
restreint Codex**, le **09/10/2026 à 01:19, heure de Paris (Europe/Paris)**.
Cette preuve est consignée d’après son compte rendu ; Codex n’a pas exécuté
cet appel et n’a pas inspecté directement le texte complet de la réponse.

- Requête : `POST http://localhost:8000/ai/generate`.
- HTTP : **200** ; `status: success` ; `provider: llama.cpp`.
- Modèle déclaré : `Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M`.
- `duration_seconds` : **6.173**.
- Usage : **47 tokens en entrée, 150 en sortie, 197 au total**.
- Réponse Qwen non vide, tronquée à la limite de **150 tokens**, selon
  l’utilisateur. Aucun texte complet ni champ `finish_reason` fourni.

Le parcours HTTP local FastAPI → llama.cpp → Qwen est ainsi validé par le
compte rendu utilisateur. Le modèle déclaré correspond à Qwen2.5-3B-Instruct
quantifié Q4_K_M ; aucune inspection indépendante des poids n’a été effectuée.
Les six tests automatisés ont été relancés après réception de cette preuve :
**6/6 réussis** avec `.venv` (0,043 s).

## DEV-001 — critères de clôture et limites

- Succès, saisie invalide, indisponibilité, timeout et réponse amont invalide :
  couverts par les tests automatisés réussis.
- Appel réel POST, HTTP 200 et contenu Qwen non vide : confirmés par l’utilisateur.
- **Aucun critère technique restant ouvert : DEV-001 clôturé.**
- Le refus réseau propre à Codex reste une limite de cet environnement, sans
  remettre en cause le test réel réussi hors Codex.
- La troncature à 150 tokens n’empêche pas la validation du transport technique.
  La qualité éditoriale, la complétude et la gestion explicite des sorties
  tronquées seront évaluées séparément.
- Cette mise à jour modifie uniquement `ETAT_PROJET.md` ; aucune migration,
  modification d’infrastructure ou de configuration appliquée.

## DEV-002 — mémoire et orchestration du développement

La priorité a été précisée par l’utilisateur : tracer les actions, décisions et
interactions, puis installer des capacités de développement et orchestrer leur
travail. L’extraction du fournisseur et les workflows métier sont reportés à
DEV-003 ; ils ne sont pas présentés comme déjà développés.

### Développé

- `workflows/memory.py` : événements JSONL append-only, horodatages UTC et dates
  d’origine, provenance, verrouillage Linux, fsync et chaîne SHA256.
- `workflows/orchestrator.py` : missions, checkpoints, preuves, contrôles tracés,
  contexte de reprise et manifestes ; création de mission sérialisée.
- `scripts/project.py`, `scripts/run_orchestrator.py` et
  `scripts/smoke_project_workflow.py` : CLI opérationnelle, préparation d’une
  session Codex et validation fonctionnelle isolée.
- Huit skills internes v1.0.0 dans `skills/`, huit agents de développement dans
  `agents/` : orchestrateur, analyste, développeur, testeur technique, testeur
  fonctionnel, relecteur, documentaliste et responsable du versionnement.
- `capabilities.lock.json` et `scripts/install_project_capabilities.py` :
  versions/empreintes et activation native par liens, sans remplacer de config.
- `external-skills.json`, `scripts/install_external_skills.py` : sources tierces
  demandées, installation officielle à SHA figé, reçus privés et activation
  séparée. Les sources tierces elles-mêmes ne sont pas téléchargées ici.
- `ORCHESTRATION.md`, `docs/EXTERNAL_SKILLS.md`, README et mémoire courante :
  procédures de reprise, provenance et limites documentées.
- Tests ajoutés : `test_memory.py`, `test_orchestrator.py`,
  `test_capabilities.py`, `test_project_cli.py`, `test_external_skills.py`.
  Les six tests API préexistants sont conservés.

Le journal masque les secrets labellisés, y compris Basic/Bearer et URL avec
mot de passe. Journal/synthèse privés 0600, dossier mémoire local 0700 ; refus des
liens symboliques pour les écritures sensibles. Le masquage reste heuristique.
La mémoire n’est ni chiffrée ni sauvegardée à distance. La chaîne détecte les
altérations, pas une réécriture complète ou une suppression de la fin du fichier.
Les anciens échanges sont des résumés rétrospectifs attribués ; aucune capture
exhaustive de Codex ni stockage du raisonnement interne n’est annoncé.

Les preuves sont liées au code testé et recontrôlées à la clôture. Un ancien
compte rendu utilisateur doit indiquer explicitement la version testée ; sa
réception ne le lie pas automatiquement au code actuel. Les manifestes locaux
et les versions déclarées ne sont pas des commits Git.

### Testé

- Validation finale : **50/50 tests automatisés réussis** (0,396 s), avec
  `.venv/bin/python -m unittest discover -s tests -v` ; résultat conservé dans
  le journal via `scripts/project.py check DEV-002` (sortie 0).
- Compilation Python réussie ; package local et empreintes validés ; huit
  skills revalidés par le validateur officiel (8/8), huit définitions TOML valides.
- Parcours CLI réel isolé : démarrage, décisions, checkpoints, contrôles,
  manifeste, clôture, génération du contexte et reprise entre processus.
  Relance finale réussie : **15/15 commandes**, clôture réelle du journal de
  test et **19 événements** vérifiés. Aucun appel Qwen durant ce parcours.
- Installation tierce et activation testées avec fixtures/mocks temporaires :
  SHA figé, dépendances, refus d’écrasement, confinement, idempotence et état
  partiel. Ces tests ne prouvent aucun téléchargement effectif.
- Revue indépendante réalisée, findings corrigés : credentials Basic,
  permissions, confinement source, lock vide, activation partielle, exemple CLI,
  preuves périmées, attribution de version utilisateur et concurrence de création.

### Blocages réels — DEV-002 non clôturé globalement

- Téléchargement `gh-fix-ci` via installateur officiel rejeté automatiquement
  avant exécution : permissions étendues interdites (`sandbox_approval=false`).
- Suite externe : sept sources référencées, **zéro installation réelle** et
  zéro reçu de téléchargement à ce stade. Choix « 1 » = sélection OpenAI
  pertinente. Voir `docs/EXTERNAL_SKILLS.md` pour les sources retenues.
- `.agents` et `.codex` en lecture seule : tentative d’activation locale sortie
  2, aucun lien créé. La découverte native des nouveaux agents/skills n’est
  pas validée ; leur lecture explicite dans le lanceur reste possible.
- `.git` inexploitable et en lecture seule : aucun commit, tag ou push.
- Le lanceur prépare bien un contexte ; une session Codex imbriquée réelle
  n’a pas été lancée depuis cet environnement restreint.

Les outils locaux sont développés et testés ; installation native, téléchargement
externe et versionnement Git restent ouverts. Aucun composant opérationnel
réinstallé, fichier `.env` affiché, configuration existante remplacée, migration
appliquée ou infrastructure modifiée. `AGENTS.md` demeure préservé.

### Autonomie et prochaine étape

L’utilisateur autorise la reprise autonome du développement et le suivi du code
après cette installation. Cette autorisation est persistée dans le journal ;
elle ne dispense pas des confirmations demandées pour les actions sensibles.
Aucun daemon autonome ni planification périodique n’a été activé.

Depuis WSL2 avec accès normal : suivre les commandes d’installation dans
`docs/EXTERNAL_SKILLS.md`, vérifier les reçus et la découverte native, puis
reprendre avec `scripts/run_orchestrator.py DEV-002 --launch`.
Le suivi du code peut continuer sur les travaux indépendants de cette activation.

**DEV-003 prévu :** extraire le fournisseur HTTP sans changer le contrat validé,
exposer le motif d’arrêt/troncature, définir les contrats de traitement et
construire un premier workflow éditorial borné avec skill versionné. Préparer
ensuite le schéma PostgreSQL et une migration révisable, sans l’appliquer.
Tout critère nécessitant Qwen réellement accessible reste ouvert jusqu’à preuve
réelle exécutée ou compte rendu utilisateur correctement attribué.

## Architecture progressive — prévue, non développée

1. DEV-001 étant validé techniquement, isoler le client dans un module fournisseur et
   définir des contrats Pydantic communs pour demandes et résultats.
2. Ajouter un orchestrateur déterministe dans `workflows/`, puis des rôles
   d’agents : cadrage éditorial, scénariste, découpage en scènes, relecteur.
   Chaque rôle appelle le même fournisseur avec sorties structurées, délais,
   budget et validation ; éviter les boucles autonomes non bornées.
3. Versionner dans Git les skills éditoriaux (`skills/<nom>/<version>/`), leurs
   instructions, schémas d’entrée/sortie et cas d’évaluation. Conserver version
   et empreinte utilisées dans chaque traitement, sans écraser une version publiée.
4. Introduire Redis et `workers/` seulement pour les traitements longs, avec
   identifiant de tâche, reprises bornées et protection contre les doublons.

## Historisation PostgreSQL — prévue, non développée

Utiliser SQLAlchemy et Alembic déjà présents. Préparer des migrations à relire,
mais ne pas les appliquer sans confirmation. Modèle proposé :

- `prompts` : texte, paramètres, version et auteur/projet.
- `treatments` : prompt source, statut, dates, modèle, workflow/skill et versions,
  durée, usage et erreur normalisée.
- `scenarios` : traitement source, version et contenu structuré.
- `scenes` : scénario source, ordre, description et contraintes.
- `results` : traitement/scène source, type, contenu ou référence MinIO,
  métadonnées et date.

Prévoir dès le schéma l’isolation par compte/projet, les clés étrangères,
transactions et identifiants d’idempotence. Stocker les gros médias dans MinIO ;
ne pas enregistrer de secrets ni de données sensibles dans les journaux.
Aucune table créée, aucune persistance ni isolation multi-compte testée à ce stade.

## Nouvelle invocation explicite de skill-installer — gh-fix-ci

Vérification réelle : skill absent des emplacements global, natif projet et vendor.
Le dossier global est non accessible en écriture. La nouvelle tentative du helper
officiel a été rejetée avant exécution par `sandbox_approval=false`.
**gh-fix-ci reste non installé.** Résultat consigné dans le journal DEV-002.
L’installation nécessite un terminal WSL2 hors de cet environnement restreint.

## OPS-REPOSITORY — création GitHub demandée, bloquée

Cible autorisée : `richardyoann/saas-directeur-editorial`, visibilité privée
préparée par défaut. Aucun dépôt créé ni contenu publié. `gh` est absent et Git
local inexploitable ; la consultation publique est inconclusive. Intégration
GitHub disponible, mais non installée/non connectée lors de la vérification.
Prochaine étape : installation/connexion GitHub, vérification des droits et
de l’existence du dépôt, puis création si les outils la permettent.
Voir `docs/REPOSITORY_SETUP.md` ; provenance et blocage consignés dans le journal.
