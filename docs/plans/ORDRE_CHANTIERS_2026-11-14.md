# Ordre des chantiers — 14 novembre 2026

Ordre de travail pour préparer et séquencer la suite du MVP Arvor. Il s'appuie sur
`ETAT_PROJET.md` (section « ÉTAT COURANT »), les limites connues des docs et
`ROADMAP_TECHNIQUE_2026-10-14.md`. Il respecte `AGENTS.md`, qui reste l'unique source
normative.

**Réserves.** L'état des PR et issues GitHub n'a pas été consulté (API inaccessible) :
l'état affiché est celui du dépôt au 28 octobre 2026. Les identifiants ci-dessous sont
**proposés** : vérifier qu'ils ne collisionnent pas avec le backlog avant de les
adopter. Les tailles (S/M/L) sont des estimations d'effort relatives, pas des délais.

## 1. Règles de séquencement

1. **Une PR = un chantier**, branche dédiée, périmètre restreint (`AGENTS.md`, procédure PR).
2. **Aucun skip accepté** ; CI Python 3.12 et 3.14, PostgreSQL jetable, sécurité, navigateur si UI.
3. **⛔ = barrière d'approbation explicite de l'utilisateur** : livraison PC (SHA complet
   exact, jamais réutilisé), suppression de ressources, migration métier, élargissement
   d'accès, modification d'infrastructure, sortie de données privées. La fusion ne vaut
   jamais autorisation de livraison.
4. **Livrer ce qui existe avant d'ajouter** : les vagues 0 à 2 stabilisent l'atelier
   mono-identité ; la vague 4 (SaaS) ne démarre qu'après la barrière B3.
5. La documentation d'état est mise à jour **dans la même PR** que chaque chantier.

## 2. Vue d'ensemble

| Vague | ID proposé | Chantier | Taille | Dépend de | Barrière |
|---|---|---|---|---|---|
| 0 | PREP-001 | Intégrer les correctifs du 14 novembre (patch) | S | — | — |
| 0 | PREP-002 | Confirmer l'état GitHub (PR #225, Dependabot, branches) | S | — | — |
| 0 | OPS-002 | Fusion groupée des 4 mises à jour pip | S | PREP-001 | — |
| 1 | MEDIA-005 | Décision et mise en œuvre Piper/FFmpeg (image ou hôte) | M | PREP-001 | B0 |
| 1 | REL-005 | Livraison PC voix + vidéo (PR #226) | M | PREP-001, OPS-002, MEDIA-005 | ⛔ B1 |
| 1 | OPS-003 | MLflow : activation dans le service déployé (PR #225 déjà fusionnée) | M | PREP-002, REL-005 | ⛔ B1 bis |
| 2 | DEV-006 | File asynchrone : worker supervisé et recette | L | REL-005 | ⛔ B2 |
| 2 | OPS-004 | Sauvegarde, restauration, rétention | L | REL-005 | ⛔ B2 bis |
| 2 | OPS-005 | Observabilité du worker | M | DEV-006 | — |
| 2 | MEDIA-006 | Orphelins : inventaire en lecture seule puis nettoyage | M | REL-005 | ⛔ B2 ter |
| 3 | SEC-005 | Quotas par identité et limitation de débit média | M | DEV-006 | — |
| 3 | WEB-002 | Backend de sessions partagé | L | SEC-005 | — |
| 3 | MEDIA-007 | Relais média en flux (si gros fichiers) | M | MEDIA-006 | — |
| 4 | SAAS-001 | IAM/RBAC, argon2, MFA, sessions persistantes | L | WEB-002, OPS-004 | ⛔ B3 |
| 4 | SAAS-002 | Isolation multi-tenant : RLS, tests IDOR hostiles | L | SAAS-001 | ⛔ migration |
| 4 | ARCH-001 | Extraction de `po_entity` en tables dédiées | L | SAAS-002 | ⛔ migration |

Ordre d'exécution recommandé : PREP-001, PREP-002 et OPS-002 en parallèle ; puis
MEDIA-005 ; puis REL-005 ; puis OPS-003 ; puis la vague 2 (DEV-006 et OPS-004 en
parallèle) ; puis la vague 3 ; la vague 4 seulement après décision B3.

## 3. Décisions à prendre avant de lancer

| Id | Décision | Bloque | Options |
|---|---|---|---|
| B0 | Piper et FFmpeg : embarqués dans l'image API ou prérequis de l'hôte PC ? | MEDIA-005, REL-005 | Image (reproductible, plus lourde) ou hôte (statu quo, variables dans `.env.example`) |
| B1 | Approuver le **SHA complet** de la livraison voix/vidéo | REL-005 | À donner après PREP-001 et OPS-002, sur le SHA final |
| B1 bis | MLflow actif dans le service déployé ? | OPS-003 | Oui (observabilité) ou différé |
| B2 | Activer la file asynchrone en production ? | DEV-006 | Après recette Qwen réelle et supervision |
| B2 bis | Durées de rétention (traitements, audits, sauvegardes) | OPS-004 | À fixer avec la classification des données personnelles |
| B2 ter | Autoriser la suppression des objets orphelins | MEDIA-006 | Après revue de l'inventaire |
| B3 | Go/no-go SaaS multi-utilisateur | Vague 4 | Tant que non décidé : atelier privé mono-identité |

## 4. Fiches de chantier

### Vague 0 — Préparation

**PREP-001 — Intégrer les correctifs du 14 novembre.** Ouvrir une PR avec
`arvor-mvp-fixes.patch` (variables d'environnement documentées, lint et
`zip(strict=True)`, gardes d'URL, état courant, cet ordre). Critères : CI verte 3.12 et 3.14,
592 tests, relecture du diff. Hors périmètre : toute livraison PC.

**PREP-002 — Confirmer l'état GitHub.** Lire en lecture seule : PR Dependabot ouvertes (la PR #225 est
constatée fusionnée le 14 novembre), branches `feat/*` déjà fusionnées. Sortie : mise à jour du
point 4 du tableau « Reste à faire » de `ETAT_PROJET.md`. Aucun changement de code.

**OPS-002 — Fusion groupée des mises à jour pip.** fastapi 0.162.0, pydantic 2.14.3,
psycopg 3.3.8, boto3 1.43.125 : 588/588 le 14 novembre en environnement local.
Critères : CI complète sur la branche groupée. Traiter à part `python:3.15-slim` : hors
matrice CI (3.12 et 3.14), il exige d'ajouter 3.15 à la matrice ou d'être refusé.
Relire `setup-python 7.1.0` : les workflows épinglent des SHA, vérifier celui de la PR.

### Vague 1 — Livrer l'existant

**MEDIA-005 — Piper et FFmpeg.** Selon B0. *Option image :* ajouter binaires et modèle
à l'image, taille et licences vérifiées, variables `ARVOR_PIPER_*` par défaut cohérentes.
*Option hôte :* documenter le prérequis dans `PRODUCTION_MEDIA_75S.md` et ajouter un
contrôle de préflight qui échoue clairement si Piper ou le modèle manque.
Critères : `scripts/smoke_video_75.py` vert ; message d'erreur explicite sans fuite de
chemin ni de secret.

**REL-005 — Livraison PC voix + vidéo (PR #226).** ⛔ B1. Prérequis : PREP-001, OPS-002,
MEDIA-005 fusionnés ; SHA complet exact approuvé. Exécution par `scripts/deploy_local.py`
via GitHub Actions ; lire `docs/mco/RUNBOOK_DIAGNOSTIC_PC.md` avant. Recette sur le poste :
voix Piper 75 s, vidéo 720×1280 avec sous-titres, lecture et téléchargement privés,
**génération d'images sd.cpp en direct** (non rejouée lors de la recette du 28 octobre),
relance après échec sur clé de tentative distincte. Preuves : reçu de recette avec SHA,
durées, empreintes ; aucun secret exposé. Retour arrière : release précédente conservée,
aucun rollback destructeur.

**OPS-003 — MLflow (PR #225 déjà fusionnée).** ⛔ B1 bis. Activer dans le service
déployé par une livraison distincte sur SHA approuvé (`client.env`, redémarrage contrôlé). Critères : panne MLflow sans blocage métier,
aucune fuite de prompt ou média, spool borné. À définir en même temps : rétention et
purge, mesure de la mémoire sous charge.

### Vague 2 — Fiabiliser l'exploitation

**DEV-006 — File asynchrone.** ⛔ B2. Suit l'« ordre de la recette privée » de la
feuille de route : (1) CI et concurrence PostgreSQL jetable ; (2) worker sur une
candidate du même SHA, file testée avec Qwen réel, mode async API éteint ; (3) capture
snapshot, audit/outbox, interruption/reprise, modèle indisponible, worker redémarré ;
(4) unité systemd supervisée ; (5) bascule avec preuve d'intégrité et rollback ;
(6) mesure des latences et du coût réels. Ne jamais activer
`EDITORIAL_ASYNC_ENABLED=true` sans worker. Aucun retry silencieux de Qwen.

**OPS-004 — Sauvegarde, restauration, rétention.** ⛔ B2 bis. Partir de ce que
`docs/mco/MINIO_MEDIA_RECOVERY.md` et le runbook PC couvrent déjà. Livrer : sauvegarde
PostgreSQL et MinIO planifiée, **restauration démontrée sur base jetable**, politique de
rétention (B2 bis), classification des données personnelles dans le texte brut, chiffrement
disque et base. Critère : un test de restauration rejouable avec reçu, sans toucher aux
données réelles.

**OPS-005 — Observabilité du worker.** Métriques : backlog en file, âge du plus ancien
job, durée et tokens, erreurs par catégorie, jobs `running` bloqués, latences base.
Logs structurés sans secret, prompt ni réponse brute. Critère : test de non-fuite et
alerte documentée sur job bloqué.

**MEDIA-006 — Objets orphelins.** ⛔ B2 ter. En deux temps : (1) script **en lecture
seule** listant les objets de tentatives échouées non référencés, avec reçu ; (2) après
revue et accord, nettoyage borné et journalisé. Jamais de suppression avant l'accord
explicite (`AGENTS.md`, suppression de ressources).

### Vague 3 — Capacité et prérequis multi-utilisateur

**SEC-005 — Quotas et limitation de débit.** Quota par identité et par tenant, distinct
selon le modèle (Qwen, sd.cpp, Piper/FFmpeg), 429 explicite, tests de monopolisation et
d'isolation. Remplace la limite actuelle par processus.

**WEB-002 — Backend de sessions partagé.** Prérequis explicite d'`AGENTS.md` avant tout
multi-instance : sessions persistantes, expiration, invalidation, rate-limit du login
partagé. Conserver CSRF, cookies `Secure; HttpOnly; SameSite=Strict`. Confirmer sur le
vrai proxy que les compteurs d'échecs sont bien par appareil.

**MEDIA-007 — Relais média en flux.** Seulement si des fichiers dépassent la limite
actuelle de 128 Mio ou si la mémoire du proxy Studio devient un problème mesuré.

### Vague 4 — SaaS (après B3)

**SAAS-001 — Identité.** Vrais utilisateurs, argon2, MFA, sessions persistantes,
consentements, rotation et invalidation. Architecture IAM/RBAC multi-tenant distincte du
MVP.

**SAAS-002 — Isolation.** RLS PostgreSQL avec `SET LOCAL` transactionnel (sans fuite de
contexte via le pool), rôles séparés lecture/écriture/migrations, tests IDOR hostiles
entre tenants. ⛔ migration : jetable d'abord, réversible, acceptation distincte.

**ARCH-001 — Extraction de `po_entity`.** Tables runs/steps/scenes/reviews avec
migrations de reprise et de retour arrière ; `po_audit` reste append-only. Une migration
par PR, jamais appliquée sans accord.

## 5. Gabarit commun à chaque PR

1. Branche dédiée, périmètre restreint, critères d'acceptation et risques écrits.
2. Tests positifs et négatifs, isolation tenant, conflits, erreurs ; RED puis GREEN.
3. Régression complète avec PostgreSQL jetable : 0 échec, 0 ignoré.
4. Documentation et commandes d'exploitation dans la même PR ; preuves par SHA et limites.
5. Aucune livraison PC tant qu'un SHA complet n'est pas approuvé explicitement.

## 6. Risques transverses

- **Activer la file asynchrone sans worker** : histoires bloquées en file.
- **Retry silencieux Qwen** : sorties dupliquées, coût et historique contradictoires.
- **Cache entre tenants** : fuite de prompts ; à exclure tant que l'isolation n'est pas prouvée.
- **DDL sur PC sans sauvegarde** : rollback difficile ; d'où OPS-004 avant toute migration.
- **SaaS en mono-identité** : absence de droits et de consentement ; d'où la barrière B3.
- **Approbation de SHA périmée** : tout nouveau SHA exige une nouvelle approbation.
