# Prise en compte de la revue externe — 14 octobre 2026

Source : document fourni « Revue de code & QA — saas-directeur-editorial ». Comparaison faite sur `main` au commit `19b7d77d74e795416576ed0685ff87a4bdc522d2` ; le rapport source disposait d'un environnement limité à 117 tests réussis et 21 ignorés, alors que la CI actuelle exécute PostgreSQL avec des fixtures isolées.

## Décisions des constats

| ID source | Décision | Motivation et preuves attendues |
| --- | --- | --- |
| S1 | Partiellement déjà corrigé ; pas de nouveau changement dans cette PR | L'anonyme est déjà interdit hors boucle locale (client + Host) et un jeton est obligatoire dès qu'une identité est configurée. La recommandation de passer **toutes** les requêtes sous `Depends(get_identity)` est une politique cible plus stricte et nécessitera la migration des clients legacy et le test d'intégration Qwen. Ne pas exposer le port sans identité. |
| F1 | **Corrigé dans cette PR** | `POST /editorial/runs/{id}/reconcile` : intervention explicite, ancienneté >600s, verrou de ligne, échec atomique avec audit/outbox et snapshot d'interruption. Deux situations testées : étape en cours et entre deux étapes. Aucune nouvelle invocation Qwen. |
| F2 | **Corrigé dans cette PR** | Le navigateur distingue échec métier confirmé (nouvelle clé) et échec réseau incertain (même clé). Une exécution `running` garde l'association avec sa clé jusqu'à verdict. |
| A1 | Hors MVP privé : backlog architecture | Identités utilisateurs, rôles, permissions de publication ; ne pas introduire le schéma proposé sans conception sécurité/RGPD et tests multi-tenant. |
| A2 | Hors MVP privé : backlog architecture | Session volatile voulue pour un worker, documentée. Redis/multi-worker après besoin réel et revue de configuration. |
| S2 | À tester avant accès mobile | Vérifier terminaison HTTPS, trusted proxy et rate limiting par client. Ne pas faire confiance à `X-Forwarded-For` non autorisé. |
| P1 | À mesurer avant migration | Index JSONB partiels et pooling pertinents sur volume réel ; `EXPLAIN (ANALYZE, BUFFERS)`, benchmark de latence, revue de migration `CONCURRENTLY` hors transaction et rollback. Aucun DDL sur les données utilisateur. |
| D1 | Différé | Numérotation de migrations et outil à introduire avant multiples versions de schéma. |
| C1 | **Amélioré dans cette PR** | `.env.example` documente toutes les variables essentielles sans secret ; README distingue ancien environnement Python local 3.14 et CI 3.12. |
| C2 | Différé | Redis/MinIO réservés aux étapes suivantes ; ne pas supprimer des volumes sans inventaire ni validation. Pinner des digests/images lors de la préparation de déploiement durable. |
| C3 | À sécuriser en exploitation | `LLM_BASE_URL` n'est pas une entrée utilisateur. Localiser l'accès Qwen au bon sous-réseau ou restreindre le pare-feu, puis évaluer token/TLS suivant l'architecture Windows/WSL. |
| L1 | Différé avec justification | Double consigne système présente dans le prompt ; sa modification change les sorties Qwen et l'empreinte documentaire. À traiter dans un incrément versionné des prompts avec validation réelle du modèle. |
| V1 | **Corrigé dans cette PR** | Limite de 64 Ko de `revised_output` au niveau Pydantic pour l'API directe ; taille du corps Studio déjà bornée. Un plafonnement ASGI global reste souhaitable si le service devient public. |
| U1 | Backlog UX | Éditeur de scène en champs guidés, régénération et polling avec contrôle de charge. Rien à publier automatiquement. |
| U2 | Déjà partiellement corrigé (PR #75) | ARIA : tabs, dialogues, focus/clavier. Reste audit WCAG 2.2 complet et ciblage des zones `aria-live` en conditions réelles. |

## Critères d'acceptation de l'incrément
1. Les exécutions `running` récentes sont conservées sans modification et sans appel LLM.
2. Une exécution périmée lors d'un appel IA devient `failed/run_interrupted` : prompt original, traitement, snapshot et audit/outbox cohérents dans une seule transaction.
3. La même réconciliation ne crée ni événement ni snapshot supplémentaire ; autre tenant interdit ; `save_step` tardif refusé.
4. Une interruption entre deux étapes devient `failed` sans inventer de seconde sortie IA.
5. L'interface permet la reprise explicite sans conserver une clé pour une erreur confirmée, mais garde la clé sur timeout/réseau ambigu.
6. CSRF, session, validation de taille et toutes les régressions existantes réussissent.
7. Validation finale avec Qwen réel, base PC réelle et configuration reverse proxy mobile avant livraison PC.

**État** : cette note décrit le code proposé dans la PR de correction. La réussite CI et l'installation PC ne sont jamais présumées.
