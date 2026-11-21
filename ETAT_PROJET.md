# État du projet

## ÉTAT COURANT — 14 novembre 2026

Synthèse établie à partir du dépôt (`main` au merge de la PR #227, 28 octobre 2026)
et d'une régression complète rejouée le 14 novembre. L'état des PR et des issues
GitHub n'a pas pu être consulté, sauf la PR #225 (fusionnée, constatée par `gh`
le 14 novembre) : à confirmer avant toute décision. Le journal
chronologique ci-dessous est conservé comme historique.

### Où en est le MVP

- **Fonctionnel :** brief → analyse → storyboard → revue humaine → images sd.cpp →
  voix Piper → vidéo FFmpeg verticale 720×1280 de 75 s, stockage MinIO privé,
  audit/outbox, Studio privé mono-identité.
- **Qualité mesurée :** 592 tests, 0 échec, 0 ignoré avec PostgreSQL jetable
  (rejoués le 14 novembre) ; `pip-audit` sans vulnérabilité ; qualification CI
  locale 16/16 et recette réelle 15/15 déclarées pour la PR #226 (28 octobre).
- **Livraison :** PR #226 (voix et vidéo) fusionnée, **aucun déploiement PC** ; le
  runtime `~/editorial-runtime/current` est inchangé. Toute livraison exige
  l'approbation explicite du SHA complet.

### Reste à faire, par priorité

| # | Chantier | Critère de sortie |
|---|---|---|
| 1 | Livrer la voix et la vidéo (PR #226) sur le PC | SHA complet approuvé, déploiement, recette voix + vidéo réelles sur le poste |
| 2 | Piper et FFmpeg hors de l'image API | Les embarquer dans l'image, ou déclarer l'hôte PC comme prérequis (variables dans `.env.example`) |
| 3 | File asynchrone (PR #78) | Worker supervisé par systemd, tests de reprise après crash, recette Qwen réelle, puis seulement `EDITORIAL_ASYNC_ENABLED=true` |
| 4 | MLflow (PR #225, déjà fusionnée) | Activation dans le service déployé par une livraison distincte sur SHA approuvé ; rétention/purge et mémoire sous charge à définir |
| 5 | Dépendances | Fusionner ensemble fastapi 0.162.0, pydantic 2.14.3, psycopg 3.3.8, boto3 1.43.125 (588/588 le 14 novembre) ; qualifier `python:3.15-slim` en CI (non testé) ; relire `setup-python 7.1.0` |
| 6 | Sauvegarde et restauration | Restauration démontrée, politique de rétention, chiffrement des prompts |
| 7 | Capacité | Quotas par identité/tenant, limitation de débit média, nettoyage des objets orphelins, relais en flux si gros fichiers |
| 8 | Observabilité du worker | Backlog, âge du plus ancien job, jobs bloqués, latences base, sans secrets ni prompts dans les logs |
| 9 | SaaS | IAM/RBAC, argon2, MFA, sessions persistantes, RLS PostgreSQL, tests IDOR entre tenants, extraction de `po_entity` |

Ordre détaillé, barrières d'approbation et critères par chantier :
[docs/plans/ORDRE_CHANTIERS_2026-11-14.md](docs/plans/ORDRE_CHANTIERS_2026-11-14.md).

Le point 9 est un prérequis à tout second utilisateur ou à toute commercialisation :
le code actuel est un atelier privé mono-identité, pas un SaaS.

### Limites assumées du MVP

- Sessions Studio en mémoire, un seul worker Uvicorn.
- Verrouillage du login par adresse IP vue par l'application : avec le `Dockerfile`
  par défaut (`--no-proxy-headers`), derrière un proxy tous les clients partageraient
  l'IP du proxy et cinq échecs bloqueraient aussi le propriétaire quinze minutes.
  L'accès mobile documenté (`--proxy-headers --forwarded-allow-ips 127.0.0.1`) sépare
  les compteurs par appareil ; à confirmer sur le vrai proxy.
- Une seule production média par processus, sans limitation de débit.
- Réservation média orpheline reprise seulement après une heure.
- Proxy Studio : média chargé en mémoire, refus au-delà de 128 Mio.

### Corrections du 14 novembre 2026

- `.env.example` complété (chaîne image/voix/vidéo, MLflow) et README corrigé
  (dossier `media_pipeline/` inexistant).
- Nettoyage lint, `zip(..., strict=True)` là où les longueurs sont garanties.
- `_scenes()` lève `RunConflict` si le storyboard et `scene_ids` diffèrent, au lieu
  de tronquer silencieusement.
- Gardes d'URL : le jeton GitHub ne part que vers `https://api.github.com/` ; les
  clients MLflow des scripts refusent tout schéma autre que http(s) ; requête SQL
  de verrouillage sans concaténation. Tests dans `tests/test_security_guards.py`.

### Documents à consolider

Les sections « Architecture progressive — prévue, non développée », « Historisation
PostgreSQL — prévue, non développée » et « OPS-REPOSITORY — création GitHub demandée,
bloquée » sont datées ; `docs/BLOCKERS.md` date du 9 octobre. À relire et à archiver
si elles sont dépassées.

## PRODUCTION MÉDIA 75 S — 28 octobre 2026

Chaîne voix/vidéo depuis un storyboard approuvé : `POST .../voice` (Piper réel),
`POST .../video` (FFmpeg, vidéo verticale 720×1280 avec audio et sous-titres),
lecture et téléchargement privés via l'API et l'onglet Studio « Voix & vidéo ».
Identifiants déterministes par scénario, réservation transactionnelle avec
audit/outbox, isolation locataire, intégrité SHA-256, échec sans rejeu
automatique, sans écrasement d'un média prêt et avec une clé de stockage par
tentative. 57 tests ajoutés (cas d'usage, PostgreSQL réel, stockage, HTTP,
navigateur) ; 588 tests réussis dans l'image CI avec PostgreSQL jetable, 19
parcours Chromium. Qualification CI locale 16/16 sur `b5449849`, provenance hôte
et intégrité des 16 journaux vérifiées (`run_id
3f17c797-0f8d-4187-acc9-a4f60cd97090`). Recette réelle 15/15 sur
PostgreSQL/MinIO jetables : voix Piper 75,000 s, vidéo H.264 720×1280 + AAC
75,000 s, sous-titres, lecture/téléchargement privés, audit atomique, relance
sur clé de tentative distincte, aucun secret exposé (images sd.cpp réutilisées,
moteur non joignable pendant la recette). Une revue indépendante a relevé une
réservation vocale pouvant rester `generating` et une relance impossible après
échec de publication ; les deux sont corrigées et couvertes par des tests. PR
#226 **fusionnée** le 28 octobre 2026 (`af47ce8e9f8bf41d69a792a30462a4b5dcf4ee8f`),
**aucun déploiement PC**. Toute livraison exige l'approbation explicite du SHA
complet. Voir [PRODUCTION_MEDIA_75S.md](docs/PRODUCTION_MEDIA_75S.md).

## MLFLOW — observabilité privée qualifiée localement, 27 octobre 2026

Serveur MLflow 3.17.2 privé sur `127.0.0.1:5000` (service utilisateur systemd
durci, un worker, authentification basique), PostgreSQL dédié `mlflow` et bucket
MinIO `mlflow-artifacts` isolés. Instrumentation Qwen, images sd.cpp, voix Piper,
piste WAV existante et export FFmpeg avec empreintes, durées, statuts et
identifiants de corrélation ; aucun prompt, média ou secret dans MLflow.
Tracker fail-open avec file/spool bornés et rejeu idempotent. Recette réelle
15/15 sur WSL, dont panne MLflow sans blocage métier et absence de fuite.
CI locale isolée 16/16 (531 tests par version Python, 18 parcours Chromium,
Gitleaks, audit de dépendances, supply-chain, revue de risques, vidéo 75 s) sur
la tête `bf293a1`. Branche poussée, PR #225 ouverte ; aucune fusion ni
déploiement PC, le runtime API déployé reste inchangé.
Voir [MLFLOW.md](docs/MLFLOW.md) et [PASSATION_MLFLOW.md](docs/PASSATION_MLFLOW.md).

## ARVOR-MEDIA-S3-INTEGRATION — 25 octobre 2026

Adaptateur S3 durci HTTPS/CA/fichiers applicatifs, image API non privilégiée et
profil Compose préparés. Tests réels MinIO et 287 tests sous Python 3.12/3.14
réussis. OpenCode local bloqué par Qwen inaccessible ; aucune attestation complète.
Aucun déploiement, volume modifié ni migration. PR draft indépendante de 214/215.
Voir [passation](docs/PASSATION_MEDIA_S3.md) et [PRD](docs/PRD_MEDIA_S3.md).

## MEDIA-004 — stockage MinIO, 16 octobre 2026

Backend optionnel pour nouvelles images, références JSONB avec audit/outbox,
lecture compatible des anciennes images sur disque ; archivage CLI privé
PNG/WAV/MP4 et restauration contrôlée ajoutés. Base inspectée :
517a62dc3a7077f9b82e9ca82d2cfcb224899ae4. Voir docs/MEDIA_004_MINIO_STORAGE.md.
Pas d'activation PC, de migration SQL, de transfert de médias historiques ni
de suppression de source. Tests S3 simulés distincts de la recette MinIO réelle.
Aucun gain de temps, infrastructure ou espace revendiqué sans mesure.

## MEDIA-003 — chaîne 80/20 et export vidéo, 16 octobre 2026

Base inspectée : 25e5d4aff298fc30c85012c75de4fc0d116821c5. Régression GitHub
38771830917 réussie ; livraison 38771922089 skipped, aucune installation
actuelle déduite. CLI hors ligne d'export MP4 vertical, voix WAV facultative,
SRT et dossier reproductible ajoutée. Tests FFmpeg réels sur médias synthétiques,
sans preuve artistique, GPU ni accès PC. Voir docs/MEDIA_003_EPISODE_EXPORT.md
pour la matrice des sept priorités, les limites et les commandes de recette.
Pas de migration, configuration runtime ou activation PC pendant ce travail.

## Lot 2 — provenance et recette images, 15 octobre 2026

Travail sur PR #87 : reçus de génération (empreintes, paramètres, personnages,
durée), classification des erreurs incertaines, conservation du PNG sur perte
d'acquittement DB et contrôle privé en lecture seule API/Studio/CLI. Aucun
nouveau modèle ni seed inventée : informations absentes du contrat actuel.
Tests ciblés locaux réussis ; régression PostgreSQL et navigateur à vérifier
sur le SHA final. Aucun déploiement PC, rendu GPU ou acceptation artistique.
Voir docs/MEDIA_002_IMAGE_RECEIPTS.md et docs/mco/IMAGE_GENERATION_RECOVERY.md.

## PO-001 — État vérifié le 12 octobre 2026 à 17:02 UTC

Cette section actualise les constats historiques conservés ci-dessous.

- Dépôt exclusif privé : richardyoann/saas-directeur-editorial, ID 1411435489. Main inspecté : a032a37f770b5f8da32d9ec24954e6f247840a90. Le clone de livraison Ubuntu-26.04 a un HEAD documentaire distinct d7690d29181471cb5791d08e591ac71dd5664815 ; aucun reset ni écrasement effectué.
- Régression main : run 38273598848 success. Livraison PC de a032a37 : run 38273667884, job install-and-live et étape candidate/régression/HTTP réel success vérifiés. Un run ultérieur 38276212946 skipped ne retire pas cette preuve historique et ne prouve aucune nouvelle activation.
- Preuves : https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38273598848 et https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38273667884. Les résultats de ces runs ne couvrent pas le futur commit de cette documentation. Aucune nouvelle sonde du processus actif exécutée pendant ce contrôle.
- WSL Ubuntu-26.04 accessible ; les constats de disque manquant et de runner absent sont historiques. Ubuntu-24.04 exclue. Le POC PR #1 reste distinct et doit être préservé.
- Le PO périodique a exécuté ses contrôles depuis le 11 octobre ; une exécution de heartbeat ne prouve pas le worker Slack métier. Aucun envoi Slack/Gmail autorisé pour ce passage.
- Le registre d'acceptations reste à qualifier par critères, SHA, date, type et revue. Une CI verte, une fusion ou un test technique réel ne constituent pas seuls une acceptation éditoriale humaine. Les historiques ne sont pas réécrits.
- Autorisation permanente : développement, diagnostic, tests, documentation, PR et fusion après revue/contrôles. Toute MEP, y compris activation PC, exige validation humaine du SHA exact. Ne pas activer une release, réactiver LOCAL_PC_ENABLED, déclencher une livraison ni migrer la production sans cette validation ; un nouveau SHA annule la validation précédente.
- Reprise : docs/AUTONOMOUS_DELIVERY.md et AGENTS.md. Pour une nouvelle version, vérifier CI et préparer dossier SHA/changements/tests/risques/retour arrière, puis attendre validation MEP. Aucun comportement d'installation ou de déploiement modifié par cette mise à jour documentaire.

## Historique conservé — constats à leur date


## EDIT-001 — Renforcement Qwen, 11 octobre 2026

- Analyse : échec réel signalé dans le suivi, cause exacte non démontrée faute de run ID/journal; livraison PC ignorée distincte d'un échec Qwen.
- Requête structurée avec message system séparé, schéma contraint, température 0,1; contrats d'entrée/sortie bornés, redirections refusées, délai total et taille de réponse limités.
- Route générique authentifiée dès configuration de l'identité privée; bootstrap local non configuré toujours historique/anonyme.
- Diagnostic en lecture seule et catégories fixes, sans secrets ni contenus privés. Versions prompt 1.1.0/workflow editorial-v1.1; aucun résultat historique écrasé.
- Validation locale finale : 106 tests, 97 réussis, 9 PostgreSQL ignorés, 0 erreur/échec. CI complète obligatoire au SHA final; Qwen réel non accessible ici.
- Aucun déploiement PC ni réglage modèle/réseau, migration ou fusion. Détail : docs/QWEN_HARDENING.md.


## DEV-005 — workflow éditorial, 11 octobre 2026

- Livraison privée renforcée : le contrôle PC doit maintenant exécuter le parcours éditorial réel, vérifier authentification, persistance, historique et rejeu idempotent avec une donnée technique synthétique par SHA. La CI complète du SHA final reste obligatoire avant fusion.
- L'utilisateur confirme base complète et LLM connectés, et autorise la progression autonome. Confirmation de son environnement, pas sonde exécutée ici.
- Base du travail : branche ops/OPS-001-pilotage-prive au SHA 0645baf9eb96d23be7eff78de70ddae4c659a77d. Fournisseur de la PR #59 repris explicitement; PR #1/#58/#59 préservées, aucune fusion.
- Nouveau parcours API privé : brief → analyse → scénario/scènes → waiting_validation; deux appels maximum, JSON strict, durée/nombre de scènes vérifiés.
- Identité privée serveur, idempotence par tenant, prompts persistés avant appel, résultats exacts et erreurs archivés, données/audit/outbox atomiques à chaque étape.
- Réutilise uniquement le schéma po_* versionné; aucune nouvelle migration, aucune preuve d'accès aux tables locales non versionnées.
- Local : 60 tests exécutés avec succès, 5 tests PostgreSQL supplémentaires ignorés faute de cible dédiée; 7 tests pilotage exécutés avec succès, 4 PostgreSQL ignorés.
- CI vérifiée au SHA 458138bbf3d1bfccd4a7a7b5e5bad330206fdfef : run 38153196125 réussi, job et étapes pilotage/PostgreSQL/API confirmés. 76 tests configurés (65 API/historique/éditorial + 11 pilotage), dont 9 PostgreSQL exécutés sur une base de service isolée. Aucun appel Qwen réel. Preuve : https://github.com/richardyoann/saas-directeur-editorial/actions/runs/38153196125.
- PR brouillon #60 reprise sur `main` afin de tester la compatibilité réelle avec les workflows de livraison; #58 reste ouverte séparément. Une nouvelle preuve `Full regression` est obligatoire après chaque nouveau SHA.
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

## DEV-003 — incrément fournisseur, 11 octobre 2026

- Baseline : main caf1725ad0087fee1a78e078047de6382d210f39, copie isolée.
- Client HTTP et validation llama.cpp extraits dans apps/api/llama_provider.py.
- Route /ai/generate et injection get_llm_client conservées; champs historiques et erreurs 422/503/502/504 préservés.
- Champs additionnels : finish_reason (nullable) et truncated (true uniquement pour length).
- Une raison absente reste inconnue : truncated=false ne garantit pas un contenu éditorial complet.
- 54 tests Linux réussis, appels modèle simulés; aucun nouvel appel Qwen réel.
- Pas de migration ni de modification WSL, infrastructure, secrets ou prototype Arvor.
- Les PR #1 et #58 restent distinctes et préservées. DEV-003 global reste ouvert : workflow éditorial et persistance non livrés par cet incrément.
- Reprise : valider sur Qwen réel le motif d'arrêt, puis préparer le workflow éditorial borné et intégrer l'historisation après revue des PR existantes.

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

## EDIT-001 — incrément validation humaine, 12 octobre 2026

API accept/reject/revise et historique paginé développés sur branche isolée; contrôle concurrent, décisions immuables, snapshots Qwen préservés et scénario/scènes courants cohérents. Aucun nouvel appel modèle ni migration métier. Tests sur base jetable : RED routes absentes, borne excessive et résultat périmé confirmés; 121 tests sans skip après correction. Revue textuelle indépendante réalisée, contrôle final des schémas ajouté; CI, livraison de ce SHA et revue à consigner après vérification. L'interface, les comptes SaaS et l'évaluation éditoriale réelle restent ouverts. Aucun critère produit accepté automatiquement.


