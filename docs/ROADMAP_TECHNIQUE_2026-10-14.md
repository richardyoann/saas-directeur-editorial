# Feuille de route technique — revue priorisée (14 octobre 2026)

## Règle de changement

Garder le MVP mono-utilisateur stable, respecter l'immuabilité des audits et ne pas modifier le PC/base réelle sans qualification. Chaque migration est indépendante, testée sur base jetable, réversible et soumise à une acceptation distincte. La revue des 3 catégories (performance, sécurité, architecture) ne signifie **pas** que tous les points sont réalisés.

| Niveau | Chantier issu de la revue | Décision et critères |
|---|---|---|
| P0 livré en code (PR #78) | Génération asynchrone | File durable PostgreSQL, worker autonome, POST 202, polling et idempotence. Flag désactivé avant installation du worker ; pas de migration. Tests de reprise/crash et recette Qwen PC encore requis. |
| P0 livré en code (PR #78) | HTTP partagé | Un client provider + un client ASGI par processus via lifespan; clients libérés proprement. Les contrôles auth/CSRF de Studio restent appliqués. |
| P0 livré en code (PR #78) | Readiness | Nouveau `/ready` DB + Qwen et `/health` conservé ; pas de faux statut de worker. |
| P1 livré en code (PR #78) | Liste SQL légère | Projetter les seuls champs utiles au catalogue ; pas d'envoi des gros snapshots storyboard complets. |
| P1 à mesurer | Index JSONB, colonnes status/date et pool psycopg | Benchmark synthétique existant, DDL candidat documenté ; demander métriques réelles, EXPLAIN buffers et taille des tables. Migrer index d'expression d'abord ; promouvoir en vraies colonnes uniquement si requêtes/historique le justifient. |
| P1 exploitation | Quotas génération par identité et tenant | Limites aujourd'hui par processus uniquement, mono-utilisateur. Définir identité/membres avant quota SaaS distribué, quota distinct par modèle et charge GPU. |
| P1 sécurité | Sauvegarde/restauration, rétention, chiffrement des prompts | Classifier données personnelles dans texte brut ; définir politique de conservation (traitements, audits, sauvegardes), suppression/anonymisation, base et disque chiffrés, restauration démontrée. |
| P1 sécurité | Supply chain + CI self-hosted | pip-audit déjà en CI. Ajouter gitleaks/bandit/ruff avec règles ciblées, runner isolé, permissions minimales, workflow de déploiement SHA figé et approbation humaine. |
| P1 coût IA | Prompt système dupliqué, max_tokens, cache | Ne pas changer sans A/B réel Qwen : versionner les prompts, tester taux de conformité JSON/longueur, conserver consignes anti-injection. Un cache éventuel doit séparer tenants, modèle, version de prompt, brief et TTL RGPD. |
| P1 observabilité | Logs structurés, métriques worker | Mesurer backlog queued, âge du plus ancien, durée/tokens, erreurs par catégorie, jobs running bloqués, latences DB. Secrets, prompts et réponses brutes exclus des logs. |
| P2 SaaS | Vrais utilisateurs, argon2, MFA, sessions persistantes | Architecture IAM/RBAC multi-tenant distincte ; rotation, invalidation, expiration d'inactivité et consentements, tests IDOR entre tenants. |
| P2 protection DB | RLS et rôle DB sans DDL | Définir la stratégie `SET LOCAL tenant` transactionnelle, éviter fuite de contexte via pool, privilégier rôles séparés lecture/écriture/migrations. Valider sur tests multi-tenant hostiles. |
| P2 architecture | Tables runs/steps/scenes/reviews, services/repos + FSM | Viser extraction incrémentale du monolithe générique `po_entity` avec migrations de reprise/rollback ; garder `po_audit` append-only. FSM statuts/événements et transitions testables. |
| P2 multi-LLM | Adapter providers, retries/backoff/circuit-breaker | Ajouter interfaces après deuxième fournisseur réel. Les retries doivent respecter l'idempotence et ne jamais reproduire un traitement ambigu sans verdict. |
| P2 configuration | `pydantic-settings` | Définir options worker/API séparées et fail-closed des secrets ; ne pas briser les tests en l'absence de config pour outils hors serveur. |
| P2 hygiène | Déplacer agents, skills, backlog, /v1 et conteneuriser | Préserver outils Codex; séparer dossiers produits/outillage sans casser workflows. Versionner API lors d'une nouvelle compatibilité ; conteneur une fois GPU/réseau Qwen validés. |
| P2 réseau | HSTS, Permissions-Policy, segmentation llama.cpp | Ajouter les en-têtes uniquement derrière TLS de confiance; Tailscale Serve privé validé en tests ASGI, pas de proxy installé sur PC. Restreindre accès serveur Qwen/WSL par pare-feu et identité si supportée. |

## Ordre de la recette privée

1. Vérifier CI du SHA et tests de concurrence en PostgreSQL jetable.
2. Démarrer un worker sur une **candidate** du même SHA et tester la file manuellement avec Qwen réel ; garder le mode async API OFF.
3. Vérifier capture snapshot et audit/outbox, interruption/reprise, modèle indisponible, worker arrêté puis redémarré.
4. Ajouter supervision et config systemd worker avant toute activation `EDITORIAL_ASYNC_ENABLED=true`.
5. Basculer sur PC seulement avec preuve d'intégrité de la release, approbation et rollback.
6. Mesurer vraies latences DB et coût Qwen avant migrations/caches ; programmer ensuite P1 et P2.

## Risques à éviter

- **Activer async sans worker** : des histoires restent en queue indéfiniment.
- **Mettre uniquement Redis en queue** : risque de double écriture entre Redis et PostgreSQL.
- **Retry silencieux Qwen** : sorties dupliquées, coût et historique contradictoires.
- **Cache entre tenants** : fuite de prompts et résultats.
- **DDL sur PC sans sauvegarde** : rollback difficile et indisponibilité.
- **SaaS commercialisé en mono-identité** : absence de droits/consentement/RGPD.
