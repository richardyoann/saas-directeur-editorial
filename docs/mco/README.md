# Base de connaissances MCO — Directeur éditorial / Arvor Studio

**Objectif :** conserver les incidents et procédures **réellement vérifiés**, réduire les diagnostics répétitifs et éviter les manipulations destructives du PC privé, de PostgreSQL et des traces éditoriales.

## Commencer ici

| Besoin | Document |
| --- | --- |
| Attestation PC read-only et smoke vidéo synthétique 75 s | [REL-004](REL_004_CI_RELEASE_PROOF_VIDEO75.md) |
| Livraison : casse de LOCAL_PC_ENABLED et JSON Python 3.14 | [Incident du 16/10](INCIDENT_2026-10-16_LIVRAISON_JSON.md) |
| Transfert MinIO incertain et reprise des médias | [MinIO médias](MINIO_MEDIA_RECOVERY.md) |
| Résultat image incertain, timeout et fichier privé conservé | [Runbook images](IMAGE_GENERATION_RECOVERY.md) |
| Comprendre l'incident du 14–15/10/2026 (symptômes, causes, corrections, preuves) | [INC-2026-10-14 — remise en service PC](INCIDENT_2026-10-14_REMISE_EN_SERVICE_PC.md) |
| Diagnostiquer une panne aujourd'hui : commandes, tests, sauvegarde, mise en service | [RUNBOOK — diagnostic et reprise PC](RUNBOOK_DIAGNOSTIC_PC.md) |
| Mécanisme de déploiement sécurisé et rollback | [AUTONOMOUS_DELIVERY](../AUTONOMOUS_DELIVERY.md) |
| Studio : sécurité, sessions et recette | [STUDIO_PRIVATE](../STUDIO_PRIVATE.md) |
| Qwen : contrats et sorties IA | [QWEN_HARDENING](../QWEN_HARDENING.md) |
| Mode async, worker PostgreSQL, idempotence | [ASYNC_EDITORIAL_WORKER](../ASYNC_EDITORIAL_WORKER.md) |
| Workflow métier, audit, snapshots | [EDITORIAL_WORKFLOW](../EDITORIAL_WORKFLOW.md) |
| Rapport d'audit technique et dette SaaS non corrigée | [QA_SECURITY_AUDIT_2026-10-14](../QA_SECURITY_AUDIT_2026-10-14.md) |
| Revue lot 1 : limites HTTP/images, erreurs Unicode/JSON, recette et dette restante | [QA_LOT1_2026-10-15](../QA_LOT1_2026-10-15.md) |

### Signatures d'entrée ou de fournisseur — revue du 15/10/2026

Sur la baseline 78cfc30d88da79f7b887977dfaf7f26bbe428048, mot de passe JSON avec
surrogate isolé ou JSON très profondément imbriqué : HTTP 500 reproduit en
ASGI. Cause confirmée : UnicodeEncodeError / RecursionError non traduits.
Correctif proposé : 422 contrôlé ; CSRF non ASCII invalide : 403. Tests isolés
dans tests/test_qa_lot1.py. Ce constat ne décrit pas une panne observée du PC.

Après livraison validée du correctif, HTTP 413 signifie corps >256 000 octets
(Studio conserve aussi son seuil 64 000) ; 408 signifie ingestion >15 s,
sans rapport avec le délai de génération. Vérifier taille et réseau avant toute
reprise. Image trop longue/lente/invalide : consulter statut et audit, ne pas
rejouer une réservation generating ou un résultat incertain. Prompt visuel
>14 000 caractères : 422 avant réservation ; raccourcir les descriptions.
Aucune requête SQL mutante ni suppression de données requise pour ces cas.

Intégration PR #88 du 16/10/2026 : un timeout mural pendant réception de l'image
conserve le code `image_provider_timeout` et le traitement de résultat incertain
de `main`. Le flux est fermé sans retry. Les garde-fous MinIO et la vérification
de l'identifiant de scène avant réservation restent présents. Voir l'actualisation
de la revue Lot 1 pour les preuves et limites ; aucune panne PC n'est déduite
d'un conflit Git ni d'un test avec fournisseur simulé.

**Règle d'or :** aucun `/health=200` ne suffit à affirmer « SaaS opérationnel ». Il faut différencier **liveness**, **readiness**, **version réellement installée**, **génération Qwen**, **persistance PostgreSQL**, **session Studio**, puis **recette utilisateur**.

## Classification et réponse MCO

| Gravité | Définition | Exemples | Conduite |
| --- | --- | --- | --- |
| **P0** | Données menacées, accès non autorisé, indisponibilité totale sans reprise sûre | volume absent/corrompu ; secrets exposés ; rollback échoué | Stopper les opérations mutantes, sauvegarder preuves, escalader immédiatement. |
| **P1** | Fonction principale indisponible, reprise connue possible | PostgreSQL refusé ; Qwen arrêté ; API non joignable ; livraison bloquée | Diagnostic read-only, correction ciblée contrôlée, recette complète avant clôture. |
| **P2** | Fonctionnement dégradé ou partiel | Studio accessible mais `/ready=503`, worker absent en mode async, erreur 409 persistante | Caractériser impact, prioriser, ne pas forcer de replay ou supprimer les runs. |
| **P3** | Non bloquant / amélioration | journal manquant, alerte insuffisante, documentation obsolète | Planifier avec propriétaire et critère de fermeture. |

La gravité est à adapter à l'impact réel : un `/ready=503` peut relever de P1 si la génération n'est plus utilisable.

## Protocole standard de traitement

1. **Constater** : date, environnement, impact utilisateur, routes/codes/erreurs, début/fin approximatifs et dernier changement connu.
2. **Geler la preuve** : SHA GitHub et release réelle, service/PID, nom du conteneur, codes HTTP, référence GitHub Actions, UUID d'exécution si pertinent ; **sans secrets et sans prompts bruts**.
3. **Isoler** : Windows vs WSL ; HTTP FastAPI vs Studio ; PostgreSQL vs modèle ; code vs configuration vs déploiement ; `skipped` GitHub vs job réellement exécuté.
4. **Émettre une hypothèse vérifiable**, la classer `confirmée`, `probable` ou `non démontrée` ; utiliser les commandes du runbook en lecture seule en premier.
5. **Sécuriser** avant opération à risque : sauvegarde valide, état des volumes, versions, fenêtre d'intervention et plan de rollback.
6. **Corriger** une seule cause confirmée par étape, conserver trace de la commande/action et sa justification.
7. **Prouver le résultat** : tests de connexion, `/ready`, routes Studio, génération Qwen, audit/historique et expérience utilisateur ; distinguer simulation et PC réel.
8. **Clore avec limites** et prévention : quoi a été vérifié, quoi reste ouvert, quelle action préventive/échéance.

## Modèle de ticket à copier pour chaque nouvel incident

```markdown
# INC-AAAA-MM-JJ-NNN — <intitulé court>

- Ouvert le (heure locale + fuseau) :
- Sévérité : P0 / P1 / P2 / P3
- Environnement et périmètre :
- Responsable / canal d'escalade :
- SHA GitHub attendu :
- SHA current, reçu last_delivery.json, MainPID :
- Impact utilisateur, métier et données :
- Dernier changement connu (code, config, PC, Docker, Qwen, réseau) :
- Premier symptôme observé / code exact :
- Étapes de reproduction (sans contenu sensible) :

## Chronologie
| Heure | Action / commande | Résultat observable | Preuve |
| --- | --- | --- | --- |

## Hypothèses
| Hypothèse | Test discriminant | Confirmée / infirmée / non démontrée |
| --- | --- | --- |

## Correction appliquée
- Prérequis / sauvegarde / risque :
- Action exacte :
- Retour arrière possible :
- Données modifiées : oui / non / non vérifié

## Vérification post-correction
- /health :
- /ready :
- /studio :
- PostgreSQL (pg_isready + requête applicative) :
- Qwen (/health + génération réelle) :
- Parcours éditorial / historique / idempotence :
- Parcours UI réel / navigateur simulé (bien distinguer) :
- SHA/reçu/runner/CI :
- Restauration de la sauvegarde testée : oui / non
- Garde LOCAL_PC_ENABLED revenue à false : oui / non / non vérifié

## Retour d'expérience
- Cause confirmée :
- Facteurs aggravants :
- Zones d'incertitude :
- Actions préventives (responsable + échéance) :
- Date de clôture et preuve :
```

## Conventions documentaires

- **Preuve directe :** sortie de commande, logs GitHub, test reproduit. Une capture peut prouver un état ponctuel, pas une surveillance continue.
- **Preuve indirecte :** succès CI, test unitaire, test navigateur avec API simulée. Indiquer toujours SHA, environnement et limite.
- **Pas d'inférence transformée en fait :** `disabled` ne prouve pas pourquoi le service s'est arrêté ; `ConnectionRefusedError` ne prouve pas un mauvais mot de passe ; `pg_restore -l` ne garantit pas une restauration.
- **Sans données personnelles/métier ni secrets :** ne versionner ni `.env`, ni base, ni prompts exacts, ni sorties Qwen, ni dump PostgreSQL, ni cookie/session.
- **Pas de mécanisme caché :** chaque changement des scripts, workflows ou contrats doit mettre à jour le runbook dans la même PR.
- **Une PR documentaire n'est pas une livraison.** Fusionner une PR sur `main` peut déclencher une CI et, si `LOCAL_PC_ENABLED=true`, une livraison involontaire ; vérifier que le flag est `false` avant fusion.

## Indicateurs minimum conseillés (à implémenter/vérifier)

| Indicateur | Fréquence indicative | Alerte / action |
| --- | --- | --- |
| FastAPI `/health` et `/ready` | Au démarrage et contrôles périodiques raisonnables | `/health=200` mais `/ready!=200` : vérifier DB, Qwen, worker si async. |
| PostgreSQL `pg_isready` + connexion applicative | Après boot / avant livraison | Refus : vérifier conteneur et journaux, pas de migration automatique. |
| Qwen `/health` et `/v1/models` | Après boot / avant génération | Timeout : détecter arrêt Windows, IP WSL changée ou port filtré. |
| Disponibilité systemd API/runner | Après reboot | Actif ≠ configuré au démarrage ; vérifier supervision. |
| Runs `queued`, `running` ancien, taux d'erreur IA | Selon cadence métier | Reconciliation explicite sans double génération. |
| Sauvegardes + restauration isolée | Selon politique de rétention choisie | Alerter si zéro octet, archive illisible ou restauration non vérifiée. |
| Flag `LOCAL_PC_ENABLED` | Avant et après **chaque** livraison | `true` hors fenêtre approuvée = risque de MEP non autorisée. |

**Responsabilités :** l'opérateur MCO valide les actions système, secrets et sauvegardes ; le responsable code revoit les correctifs ; le responsable éditorial valide le contenu produit. Une CI verte ne vaut pas recette utilisateur ni acceptation métier.
