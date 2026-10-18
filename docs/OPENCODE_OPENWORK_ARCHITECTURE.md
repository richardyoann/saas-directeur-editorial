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
