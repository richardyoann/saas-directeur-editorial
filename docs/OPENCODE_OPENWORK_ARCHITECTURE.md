# Architecture Arvor — OpenCode et OpenWork

Statut : proposition sur branche, non installée et non livrée sur PC (18/10/2026).

## Frontières

- Arvor : FastAPI, PostgreSQL, Studio HTML/CSS/JS, Qwen éditorial, génération d'images et MinIO. Aucun changement de données métiers.
- OpenCode : agent de développement local sous WSL Ubuntu 26.04, distinct du SaaS, capable de proposer des changements sur une branche Git séparée et d'analyser des tests.
- OpenWork : interface facultative au-dessus d'OpenCode ; pas de dépendance pour la CI/CD, pas de partage distant par défaut.
- GitHub : dépôt, PR et version exacte. Le runner privé `editorial-pc` reste l'unique exécutant de livraison.

## Flux cible

```text
Besoin / Issue -> OpenWork (optionnel) -> OpenCode (orchestrateur)
                          |                -> analystes architecture, UX/UI, sécurité
                          +-> worktree et PR (modifications soumises à revue)
                          +-> tests locaux déterministes (PostgreSQL jetable)
PR revue -> merge main -> autorisation humaine du SHA complet
          -> GitHub Actions manuel / runner PC
          -> revalidation qualité et sécurité locale
          -> deploy_local.py / candidat / probes HTTP / rollback
          -> Arvor local privé
```

## Sécurité

1. Les agents sont en lecture seule par défaut. Développement possible sur worktree isolé, sans accès aux bases métier, secrets, volumes, fichiers privés ou dossiers de release.
2. Aucun agent, modèle local ou OpenWork ne peut s'auto-attribuer l'approbation d'un SHA, contourner `LOCAL_PC_ENABLED`/`LOCAL_PC_APPROVED_SHA`, merger ou déployer.
3. Résultat LLM != validation. Les tests et scans doivent produire un code de sortie déterministe et un reçu lié au SHA réellement testé.
4. Les contrôles obligatoires sont rejoués par le runner avant déploiement, sans croire les rapports d'agents. Les échecs bloquent. Ancienne release préservée et rollback testé.
5. Services OpenCode/OpenWork : loopback privé, pas de `0.0.0.0`, aucun MCP distant ou partage de données activé sans accord.

## Profil matériel / LLM

Machine : Ryzen 5 5500, 32 Go RAM, RX 580 8 Go, Windows 11 / WSL2. Premier choix conservateur : Qwen3-4B-Instruct-2507 GGUF Q4_K_M via llama.cpp Vulkan **Windows**, port distinct 8083, contexte initial 8192. La compatibilité réelle des outils OpenCode doit être validée par un appel `tool_calls` ; un modèle 4B ne garantit pas des corrections complexes. Alternative selon benchmarks : Qwen2.5-Coder-7B-Instruct Q4_K_M. Les tests du logiciel restent sans LLM.

## OpenWork

Le projet OpenWork retenu est `different-ai/openwork` : une application indépendante, à installer séparément seulement après vérification des binaires, de la licence et du mode de fonctionnement local. OpenCode CLI suffit pour la première migration. Pas d'installation d'OpenWork implicite lors de la livraison du SaaS.

## Contrôle et état

Phase 1 : documentation, script d'installation et test modèle. Phase 2 : gate qualité local et migration de CD. Phase 3 : essais réels PC, branche protégée, preuves et activation manuelle. Aucune étape n'est annoncée comme exécutée sur PC sans constat du runner.

Documents connexes : `AGENTS.md`, `docs/AUTONOMOUS_CI.md`, `docs/mco/RUNBOOK_DIAGNOSTIC_PC.md`.

Références : https://opencode.ai/v2/docs/ ; https://opencode.ai/v2/docs/agents/ ; https://github.com/different-ai/openwork

## Analyse automatique apres chaque commit Git

L'installation d'OpenCode seule ne lance pas ses agents apres les commits. Activer explicitement le hook du projet dans WSL :

```bash
cd ~/arvor-opencode
git fetch origin feat/OPS-OPENCODE-LOCAL-CI-20261018
# Rester sur un checkout propre lors de l'actualisation du worktree.
git switch --detach origin/feat/OPS-OPENCODE-LOCAL-CI-20261018
bash scripts/install_opencode_autoreview.sh
```

Le hook Git `post-commit` appelle `scripts/opencode_auto_review_commit.sh` **sans ralentir le commit**. Il travaille sur un worktree temporaire du SHA exact, avec un verrou pour ne pas exécuter plusieurs revues simultanément. Les rapports et statuts sont conservés sous `~/.local/state/arvor-opencode/reports/<SHA>.md` et `<SHA>.status`. Le hook est commun aux worktrees qui partagent le même dépôt Git, mais ne s'applique pas aux commits faits directement sur GitHub ou sur une autre machine.

**Par défaut, seul le modèle local `arvorlocal/coder` est autorisé**. Si le serveur Windows 8083 est arrêté, la revue est notée `skipped local_model_offline` sans utiliser de crédits de modèle hébergé. Un autre modèle (gratuit ou payant) n'est utilisé que si l'utilisateur renseigne volontairement son identifiant dans le fichier local `~/.config/arvor-opencode-review-model`, par exemple `fournisseur/modele`. Il faut alors vérifier les limites et les frais éventuels : un déclenchement par commit peut consommer des tokens distants.

```bash
# Inspecter le statut de la derniere revue
ls -lt ~/.local/state/arvor-opencode/reports/*.status | head
# Voir un rapport : remplacer SHA par un identifiant de commit reel
SHA="$(git rev-parse HEAD)"
cat "$HOME/.local/state/arvor-opencode/reports/$SHA.status"
cat "$HOME/.local/state/arvor-opencode/reports/$SHA.md"
```

La revue n'est pas un test automatisé et ne remplace pas la commande de QA ni une revue humaine. Aucun `git push`, merge, déploiement, ouverture de PR ou publication de rapport n'est déclenché automatiquement. Lorsqu'un autre hook `post-commit` existe déjà, le script d'installation refuse de le remplacer : réaliser une intégration manuelle sans écraser les hooks existants. L'arrêt du serveur local, la déconnexion WSL ou un quota de fournisseur peuvent empêcher une revue de finir ; vérifier le fichier `.status` plutôt que supposer qu'elle est réussie.
