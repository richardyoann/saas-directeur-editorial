# Archive du README avant rationalisation

Historique documentaire conservé pour traçabilité ; se référer au README racine pour le démarrage actuel.

# Directeur éditorial IA

## Base de connaissances MCO

Pour analyser une panne sans réinstaller ou supprimer les données :
**[index MCO et modèle de ticket](docs/mco/README.md)**,
**[rétrospective de la remise en service du 14–15/10/2026](docs/mco/INCIDENT_2026-10-14_REMISE_EN_SERVICE_PC.md)**,
**[runbook de diagnostic PC](docs/mco/RUNBOOK_DIAGNOSTIC_PC.md)**.
Ces documents séparent constat/diagnostic/action/preuve, Windows/WSL, code/version/dépendances, test simulé/recette réelle, et décrivent les garde-fous PostgreSQL et GitHub.

## Diagnostic et Git dans l’environnement restreint

```bash
.venv/bin/python scripts/diagnose_project.py
bash scripts/git_project.sh status
```

Le diagnostic vérifie les accès sans afficher d’identifiants. Git utilise un
dépôt alternatif lorsque `.git` est protégé. Voir `docs/BLOCKERS.md` pour les
corrections locales, restrictions restantes et commandes de reprise WSL2.

API FastAPI relayant les demandes éditoriales à un serveur llama.cpp compatible
avec `/v1/chat/completions`. Python relevé sur le PC lors d'un ancien diagnostic : 3.14.4 ; CI GitHub : Python 3.12. Les dépendances applicatives
observées sont consignées dans `requirements.txt`; `.venv` est déjà opérationnel.

## Développement

Depuis la racine du dépôt :

```bash
.venv/bin/python -m uvicorn apps.api.main:app --reload
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_llm_integration.py
```

L’application charge le fichier `.env` à la racine, sans écraser les variables du
processus. `LLM_BASE_URL` doit désigner la racine du serveur llama.cpp, sans ajouter
`/v1/chat/completions`. Ne versionnez pas `.env`. `.env.example` fournit un exemple
d’adresse locale qui doit être vérifié dans votre environnement.

`GET /health` vérifie uniquement l’API. `POST /ai/generate` attend un `prompt`
textuel non blanc et accepte `max_tokens` entre 1 et 2048 (250 par défaut).

```bash
curl -sS http://127.0.0.1:8000/ai/generate \
  -H "Authorization: Bearer $EDITORIAL_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Propose un titre sur les jardins urbains.","max_tokens":64}'
```

Le script d’intégration exécute ce POST via le transport ASGI, sans serveur HTTP
local, avec un véritable appel réseau amont. Il affiche le résultat et échoue si
le statut ou le contenu sont invalides. Il ne confirme pas à lui seul l’identité
des poids du modèle ; vérifier également le modèle chargé côté llama.cpp.

PostgreSQL, Redis et MinIO sont déclarés dans `compose.yml`; leur disponibilité
n’a pas pu être vérifiée depuis cet environnement. Voir `ETAT_PROJET.md` pour les
résultats, blocages et étapes prévues.

## Mémoire et orchestration du développement

Consulter `ORCHESTRATION.md` et `docs/memory/CURRENT.md` avant une reprise.

```bash
.venv/bin/python scripts/project.py context
.venv/bin/python scripts/project.py status DEV-002
.venv/bin/python scripts/project.py check DEV-002
.venv/bin/python scripts/smoke_project_workflow.py
```

Le journal local conserve actions, décisions, interactions résumées et preuves.
Le workflow guide huit rôles de développement et distingue simulation, test réel
et compte rendu utilisateur. La capture complète des sessions Codex est absente.

Les capacités internes sont dans `skills/` et `agents/`, avec versions et
empreintes dans `capabilities.lock.json`. Voir `docs/EXTERNAL_SKILLS.md` pour la
suite tierce demandée et l’installation WSL2 préparée ; elle reste bloquée ici.
Les manifestes locaux ne sont pas des commits Git. Aucune migration appliquée.

## Motif d'arrêt de la génération (DEV-003)

`/ai/generate` conserve ses champs historiques et ajoute `finish_reason` et
`truncated`. `length` signifie que la limite de tokens a interrompu la sortie;
le client doit permettre une revue ou une relance explicite. Aucune relance
automatique n'est déclenchée. Si le serveur omet le motif, il vaut `null` et
`truncated` vaut `false`; cela ne constitue pas une preuve de complétude.
Le fournisseur HTTP est isolé dans `apps/api/llama_provider.py`.

## Workflow éditorial privé (DEV-005)

`POST /editorial/runs` produit un scénario découpé en scènes et conserve les prompts, résultats et erreurs dans le schéma PostgreSQL audit existant. Deux appels IA maximum; sorties structurées validées, revue humaine obligatoire et renvoi idempotent. Consultation : `GET /editorial/runs/{uuid}` et `/history`. Configuration, preuves et limites : [guide](docs/EDITORIAL_WORKFLOW.md).

## Arvor Studio — interface privée WEB-001

La première interface navigateur se trouve sur `/studio` (par défaut `http://localhost:8000/studio`). Elle comprend bibliothèque paginée, création de brief, analyse, storyboard, historique et validation éditoriale. Définir `EDITORIAL_WEB_PASSWORD` (secret distinct, 32 caractères minimum), en plus de la configuration éditoriale existante. Un seul worker et une exposition HTTP limitée à la boucle locale sont requis; pour un téléphone, configurer et vérifier HTTPS via un reverse proxy. Voir [guide de sécurité, démarrage et recette](docs/STUDIO_PRIVATE.md). Aucune image ni production vidéo intégrées à cette étape.


## Diagnostic d'une génération interrompue (F1/F2)

Les générations suivent une règle de **non-relance automatique** de Qwen. Après arrêt brutal, une exécution peut rester en état `running`. Depuis la fiche Studio, **Vérifier un blocage** lance `POST /studio/api/runs/{uuid}/reconcile` sous session privée/CSRF. Si le dernier début d'étape date de plus de 10 minutes, le backend enregistre un échec `run_interrupted` et conserve le prompt, le résultat interrompu (vide), l'audit et l'outbox en une transaction. Une génération récente n'est pas modifiée.

La première erreur réseau **incertaine** conserve sa clé d'idempotence afin de ne pas lancer une génération en doublon. Après un échec terminal **confirmé**, une nouvelle tentative du même brief utilise une nouvelle clé. Il faut ouvrir explicitement une nouvelle tentative ; les versions anciennes restent consultables. La route de contrôle ne redémarre jamais le modèle. Tests PostgreSQL dédiés et parcours navigateur documentés dans [la note de prise en compte](docs/REVUE_COMPLEMENTAIRE_2026-10-14.md).

La route `/ai/generate` exige désormais une identité et un jeton API **même sur `localhost`**. Configurer `EDITORIAL_API_TOKEN`, `EDITORIAL_TENANT_ID` et `EDITORIAL_ACTOR_ID` avant tout diagnostic. Le script `scripts/check_llm_integration.py` utilise également ce jeton et n'affiche pas sa valeur.


## Priorités MVP privé : téléphone, performances et édition guidée

- **Téléphone** : pas d'accès public ouvert. Préparer un reverse proxy HTTPS privé via Tailscale Serve, avec Uvicorn `--proxy-headers --forwarded-allow-ips 127.0.0.1` (proxy local exclusivement), cookie `Secure`, contrôle CSRF et validation du `X-Forwarded-For`. Aucun tunnel n'est activé automatiquement. Procédure : [MOBILE_PRIVATE_ACCESS.md](docs/MOBILE_PRIVATE_ACCESS.md).
- **PostgreSQL** : mesurer `EXPLAIN (ANALYZE, BUFFERS)` avant/après index sur **tables temporaires dans une base jetable**. Les index proposés et l'étude d'un pool n'affectent pas la base réelle sans une migration validée. [SQL_BENCHMARK.md](docs/SQL_BENCHMARK.md).
- **Édition** : sélectionner « Réviser » pour obtenir des champs guidés pour l'analyse et chaque scène (titre, synopsis, narration, personnages, plans, images, sons). La durée totale est validée, les données restent conformes au schéma Pydantic et toute révision conserve audit/versions. L'éditeur JSON brut n'est plus requis.

## MCO — Diagnostic passif de la file éditoriale

Le script `scripts/diagnose_editorial_queue.py` donne des compteurs agrégés par état, les âges des runs `queued`/`running` et des alertes sans contenu métier. Il travaille uniquement en lecture seule sur le tenant configuré, n'appelle pas Qwen et ne réconcilie aucun run. Voir [procédure et limites](docs/EDITORIAL_QUEUE_MONITORING.md). Son usage sur le PC suppose la livraison distincte d'un SHA validé.

## Revue CI/CD et préqualification automatiques (CI-002)

Sur chaque PR, **Automated PR risk review** signale les chemins sensibles,
migrations, modifications CD et absence de tests ou documentation. L'audit des
dépendances couvre toutes les PR, `main` et un contrôle hebdomadaire. Après les
runs GitHub, un workflow séparé, exécuté depuis `main` de confiance, produit
des commentaires de triage des échecs ou un dossier de release dans le résumé
des Actions. **Aucun correctif arbitraire, aucune MEP et aucune activation PC
n'est effectuée automatiquement par ces nouveaux workflows.** Voir
[fonctionnement, permissions, tests et limites](docs/AUTONOMOUS_CI.md).

## Personnages et images privées (MEDIA-001)

L'onglet **Personnages & images** présente les fiches de personnages et les
prompts visuels produits à partir du storyboard Qwen. Après validation humaine
complète, une image par scène peut être demandée explicitement à un serveur de
synthèse d'images **distinct** de Qwen, compatible OpenAI Images (`b64_json`,
PNG). L'image est conservée hors du dépôt et des releases, avec métadonnées,
audit et contrôle d'accès via Studio. L'absence de serveur d'images retourne
503 ; **aucun modèle graphique n'est installé ou supposé opérationnel**.
Guide : [intégration personnages / images, configuration privée et tests](docs/MEDIA_001_VISUAL_INTEGRATION.md).

## Moteur graphique local : SD.cpp / Vulkan (MEDIA-002)

Le pont d'images utilise désormais la forme documentée de l'API `sd-server` :
`POST /v1/images/generations` (`output_format=png`). Une vérification en
lecture seule de `GET /v1/models` et un contrat HTTP simulant trois scènes
complètent les tests PostgreSQL. La solution GPU RX 580 est une piste de
recette, **pas une installation déjà réalisée**. Diagnostic Windows, construction
facultative et conditions réseau WSL :
[MEDIA_002_SDCPP_VULKAN.md](docs/MEDIA_002_SDCPP_VULKAN.md).

## Livraison privée sans écriture métier (REL-002)

La recette candidate de Qwen utilise exclusivement la base PostgreSQL jetable du job ; après bascule, seuls les contrôles GET santé/readiness/liste et les opérations de session Studio volatile sont utilisés. Les verrous GitHub `LOCAL_PC_ENABLED=true` et `LOCAL_PC_APPROVED_SHA=<SHA complet accepté>` doivent tous deux être activés, et le SHA doit disposer de sa CI et de son audit de dépendances réussis. Voir [REL_002_SAFE_DELIVERY.md](docs/REL_002_SAFE_DELIVERY.md). La fusion et les tests ne valent pas livraison PC.

# Export vidéo hors ligne

Après validation humaine du scénario, assembler les PNG locaux en MP4 vertical,
avec voix WAV facultative et dossier reproductible :
[guide MEDIA-003](docs/MEDIA_003_EPISODE_EXPORT.md).
Prérequis supplémentaire : FFmpeg et ffprobe dans Ubuntu 26.04 ; aucune
installation automatique sur le PC.

