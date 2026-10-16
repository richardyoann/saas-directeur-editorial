# QA-SEC — Plan de remédiation contrôlée (16/10/2026)

Portée : base `main` SHA `1aeddcb8e496510034a272484f9bde955fd11fb0`, PR corrective #98, environnement privé mono-identité. Aucun déploiement PC autorisé par ce document.

## Traité dans la PR #98
| ID audit | Traitement |
|---|---|
| SEC-02 | `/ready` : cache 2 s, sondes PostgreSQL/LLM bornées et lecture des tables requises |
| SEC-03 | OpenAPI configurable, désactivé par défaut |
| DATA-01 | `begin_step` et `save_step` ignorent les entités supprimées, contrôlent `editorial_run` |
| DATA-02 | Version de traitement contrôlée avec `SELECT ... FOR UPDATE`, plus d'hypothèse version 1 |
| API-01 | Dépôt GitHub choisi par configuration serveur, pagination maximum trois pages et indicateur de troncature |
| INFRA-01 | Image MinIO épinglée à une release officielle existante ; revérifier le digest sur l'hôte avant déploiement |
| INFRA-02 | Redis placé dans un profil optionnel (ne pas supprimer les données/services existants) |
| GOV-01 | Instructions agents unifiées, historique archivé, README recentré |
| QA | Tests de vérification du schéma, des verrous, de la profondeur métier et du cache de disponibilité |

## Réduction de risque déjà présente
- SEC-01 : Tailscale Serve et Uvicorn ont déjà une procédure de proxy de confiance avec `--forwarded-allow-ips 127.0.0.1` et un test d'intégration `tests/test_mobile_proxy.py`. La validation sur le proxy **réel** reste obligatoire avant l'accès distant.
- SEC-04 : les sessions Studio restent en mémoire ; contrat strict **un seul worker et réseau privé**. Un stockage partagé et une politique multi-sessions exigent un projet séparé.
- API-02 : conserver provisoirement l'endpoint 403 : fermeture explicite sécurisée d'une ancienne API; ne pas le rouvrir silencieusement.
- Analyse des dépendances : `.github/workflows/security-deps.yml` audite les dépendances Python ; ne prouve pas la sécurité des conteneurs, du modèle, de FFmpeg ou de l'historique Git.

## Non résolu / dépendant de décisions métier
- Comptes, invitations, RBAC par utilisateur et isolation multi-tenant : issue #99.
- Contrats d'abonnement, webhooks de facturation, politique RGPD : issue #100.
- Publication métier, calendrier éditorial, CMS et tests médias : issue #101.
- Parité visuelle complète avec l'application de référence : PR #97 (brouillon indépendant).
- Core Web Vitals, charge, audit WCAG 2.2 AA et scan de secrets sur tout l'historique : à exécuter sur un environnement de recette, aucun score fabriqué.
- Mesure SQL JSONB : conserver la campagne benchmark sur base jetable avant tout index ou migration.

## Garde-fous de livraison
1. Les tests 3.12 et 3.14, avec PostgreSQL de test, la sécurité des dépendances et le navigateur doivent être verts au **SHA final**.
2. Vérifier la recette du cockpit GitHub lorsque `EDITORIAL_GITHUB_REPOSITORY` est présent et lorsqu'il est absent.
3. Vérifier la version/digest MinIO actuel et prévoir une sauvegarde avant remplacement du conteneur, car l'épinglage du tag change la référence Compose.
4. Préserver `last_delivery.json`, volumes et secrets ; ne jamais exécuter `docker compose down -v`.
5. Fusion GitHub ≠ autorisation MEP sur PC : nouvelle validation explicite du SHA exact.
