# Orchestration du développement

## Reprendre une mission

Lire `AGENTS.md`, `ETAT_PROJET.md`, ce document puis
`docs/memory/CURRENT.md`. Vérifier les preuves du journal avant de reprendre une
conclusion. `AGENTS.md` reste préservé conformément à la demande initiale.
Ses mentions d’absence de tests/manifeste correspondent à l’état initial ;
les commandes actuelles sont documentées ici et dans le README.

```bash
.venv/bin/python scripts/project.py verify
.venv/bin/python scripts/project.py context
.venv/bin/python scripts/project.py status DEV-002
```

Le journal est la mémoire du **développement**. Il ne constitue pas encore
l’historisation PostgreSQL des prompts et traitements métier.

## Agents et skills locaux

Les sources maintenues sont `agents/*.toml` et `skills/*/SKILL.md`. Leur première
version est **1.0.0** ; `capabilities.lock.json` contient les versions et empreintes.
Une évolution publiée doit modifier la version concernée et le lock après revue.
Conserver les versions historiques dans Git lorsqu’il est accessible ; ne pas
présenter les empreintes locales comme des commits.

| Agent | Responsabilité | Skill principal |
| --- | --- | --- |
| orchestrator | Objectif, délégation, critères et reprise | editorial-orchestrator |
| analyst | Audit et critères observables | editorial-memory |
| developer | Changements ciblés FastAPI et workflows | editorial-fastapi |
| technical_tester | Tests automatisés et erreurs | editorial-technical-tests |
| functional_tester | Parcours réels et provenance des preuves | editorial-functional-tests |
| reviewer | Bugs, confidentialité et régressions | editorial-fastapi |
| documenter | État développé/testé/prévu et décisions | editorial-documentation |
| versioner | Diff, empreintes, préparation des commits | editorial-versioning |

`editorial-postgres-design` couvre la conception de la future persistance sans
appliquer de migration. Les agents métier de cadrage/scénarisation/relecture
exécutés par Qwen restent prévus séparément.

## Parcours d’une mission

```bash
.venv/bin/python scripts/project.py start DEV-003 --objective "Objectif précis"
.venv/bin/python scripts/project.py record DEV-003 --kind decision \
  --actor orchestrator --summary "Choix et motif" --source agent
.venv/bin/python scripts/project.py status DEV-003 --stage analysis \
  --outcome passed --summary "Audit et critères consignés"
.venv/bin/python scripts/project.py check DEV-003
```

Les étapes sont analyse, développement, tests techniques, tests fonctionnels,
revue, documentation et versionnement. L’orchestrateur utilise les outils de
sous-agents disponibles ou exécute successivement leurs rôles. Pour une
exécution parallèle, attribuer des fichiers distincts et consigner chaque
handoff ainsi que son résultat. Les fiches seules ne lancent aucun agent.

Une preuve fonctionnelle exécutée par l’outil peut être enregistrée ainsi,
avec un résumé sans secret et une provenance fidèle :

```bash
.venv/bin/python scripts/project.py record DEV-003 --kind evidence \
  --actor functional_tester --source tool --summary "Résultat du test réel exécuté" \
  --data-json '{"gate":"functional_test","outcome":"passed","scope":"real_http"}'
.venv/bin/python scripts/project.py status DEV-003 --stage functional_test \
  --outcome passed --source tool --summary "Preuve réelle consignée"
```

`source=user` indique un compte rendu, sans inspection indépendante. Pour un
compte rendu utilisateur, fournir explicitement `implementation_sha256` du code
réellement testé dans `--data-json` (empreinte affichée par `status`). Si cette
version n’est pas confirmée, consigner la preuve historique sans valider le gate
courant. L’outil n’attribue pas automatiquement un ancien compte rendu au code
actuel. Une preuve
`source=simulated` ne satisfait pas le gate fonctionnel réel. Si aucun parcours
fonctionnel n’est concerné, justifier `not_applicable` explicitement. Les tests
techniques restent obligatoires. La CLI contrôle la présence, la provenance
et la version des preuves ; elle ne garantit pas la véracité d’un compte rendu.

Après revue et documentation, créer le manifeste, valider l’étape puis clôturer
seulement si tous les critères et blocages requis sont résolus :

```bash
.venv/bin/python scripts/project.py manifest DEV-003
.venv/bin/python scripts/project.py status DEV-003 --stage versioning \
  --outcome passed --summary "Empreintes locales vérifiées ; statut Git précisé"
.venv/bin/python scripts/project.py close DEV-003 --summary "Critères satisfaits"
.venv/bin/python scripts/project.py context --write-current
```

Les preuves techniques/fonctionnelles sont liées à une empreinte des fichiers
applicatifs et capacités. Un changement invalide leur réutilisation à la clôture.
La clôture vérifie également le fichier manifeste et les sources correspondantes.
Les statuts intermédiaires restent historiques ; relancer les validations après
une modification. Les documents de synthèse et le journal mutable sont exclus
respectivement de l’empreinte technique et du manifeste pour éviter les boucles.

## Traçabilité et confidentialité

`docs/memory/events.jsonl` est append-only via l’outil : horodatage UTC, identifiant
UUID, mission, acteur, type, résumé, données, provenance et chaîne SHA256.
Un verrou distinct empêche deux coordinateurs de créer simultanément la même mission.
`occurred_at` conserve l’heure d’un événement rapporté ; `recorded_at` indique
l’écriture réelle. Un verrou Linux sérialise lecteurs et écrivains ; les écritures
sont synchronisées sur disque. Une corruption bloque la lecture et l’écriture
sans réparation automatique. SHA256 détecte une altération, pas une réécriture
malveillante complète ni une suppression de la fin du journal.

Consigner les demandes/corrections utilisateur, commandes, fichiers concernés,
choix et motifs, délégations, résultats, blocages et prochaine action. `check`
journalise ses commandes et résultats ; les autres messages/outils demandent
un résumé via `record`. Aucune capture automatique exhaustive de Codex, ni
stockage du raisonnement interne. Les synthèses anciennes sont rétrospectives
et identifiées comme telles.

Ne jamais fournir `.env` ou des secrets au journal. Le masquage est un filet de
sécurité heuristique, pas une garantie pour des secrets sans marqueur. La mémoire
locale est non chiffrée ; journal privé et synthèse locale doivent rester privés.
Aucune purge ou suppression automatique. Une sauvegarde ou historisation distante
reste à organiser avant usage multi-utilisateur.

## Activation native et lanceur

```bash
.venv/bin/python scripts/install_project_capabilities.py --check
.venv/bin/python scripts/install_project_capabilities.py --apply
```

L’activation ajoute uniquement des liens dans `.agents/skills/` et `.codex/agents/`.
Elle préserve les fichiers/configurations existants et s’arrête au préflight en
cas de conflit ou lecture seule. Ces dossiers sont actuellement **en lecture
seule dans Codex** : activation non réalisée. Exécuter `--apply` depuis WSL2 avec
les droits normaux, puis vérifier leur découverte dans une prochaine session.
Aucun téléchargement externe nécessaire pour ce package adapté au dépôt.

La découverte des skills par dossiers/liens et les définitions natives d’agents
suivent la [documentation skills](https://learn.chatgpt.com/docs/build-skills)
et la [documentation sous-agents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
Leurs capacités réelles dépendent de la version et des permissions du runtime.

Un lanceur permet aussi de charger explicitement les instructions locales :

```bash
.venv/bin/python scripts/run_orchestrator.py DEV-002
.venv/bin/python scripts/run_orchestrator.py DEV-003 \
  --objective "Objectif précis" --launch
```

Sans `--launch`, il affiche le contexte préparé ; avec cette option, il ouvre
une session Codex interactive avec l’authentification et les protections
habituelles. Le lancement réel n’est pas testé dans l’environnement restreint.
Aucun modèle imposé, infrastructure modifiée ou droit élevé demandé.

## Observabilité MLflow

Le suivi des générations est opt-in et ne remplace jamais PostgreSQL. Pour une
mission qui produit des médias ou des textes :

```bash
systemctl --user status arvor-mlflow.service
.venv/bin/python scripts/mlflow_healthcheck.py \
  --env-file ~/.config/arvor-mlflow/client.env --wait 30
```

Le détail de l'architecture, des données autorisées, de la panne et du rejeu est
dans `docs/MLFLOW.md`. Ne jamais activer `ARVOR_MLFLOW_ENABLED` sur le service
API déployé sans autorisation de livraison du SHA exact ; ne jamais copier
`client.env` ni les secrets dans un dépôt, un ticket ou un journal.

## Production voix et vidéo 75 s

Le parcours Studio « Voix & vidéo » appelle des routes privées qui exigent un
storyboard approuvé et des images prêtes pour le montage. Une seule production
média tourne à la fois ; un échec est historisé et n'est jamais rejoué
automatiquement. Les médias prêts sont immuables et restent dans le stockage
privé existant. Variables et contrat : `docs/PRODUCTION_MEDIA_75S.md`.
Ne pas lancer de recette sur la base métier : utiliser une base et un bucket
jetables, et ne jamais publier les identifiants de locataire.

## Autorisations

Demander confirmation avant suppression de données, migration appliquée,
modification d’infrastructure ou remplacement de configuration existante.
Préserver `.env`, Compose, modifications Git et composants opérationnels.
Git inaccessible : produire un manifeste local et signaler le blocage ; ne pas
initialiser ou remplacer `.git`, ni créer un commit supposé.

## Economie de contexte Codex

Voir docs/TOKEN_ECONOMY.md : profils .codex/agents, deux sous-agents maximum, contexte minimal et mesures comparables. Aucune modification du runner ni des controles de livraison.
