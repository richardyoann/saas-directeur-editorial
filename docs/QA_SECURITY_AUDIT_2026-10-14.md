# Audit senior full-stack / QA — Directeur éditorial — 14/10/2026

## Référence et méthode
- Point de départ : `main` à `6b2f3f04a8c65c8c9b47e1102bb62e937c52e417`.
- Inventaire Git complet du HEAD : 102 blobs/fichiers sur 128 entrées (répertoires inclus).
- Lecture des principales couches API, schéma SQL, audit/outbox, déploiement, frontend, tests et CI.
- Détection indicative de secrets (signatures GitHub/OpenAI/Slack/AWS/PEM) sur 102 blobs de `main` et sur les ajouts de 42 commits visibles dans l'historique de `main` : aucun motif à forte confiance. **Ce contrôle n'est pas un scan de toutes les branches ni une analyse d'entropie complète.**
- Dépendances directes vérifiées depuis `requirements.txt` ; audit de vulnérabilités transitives ajouté à CI pour confirmation.
- Tests de référence avant remédiation : 128 Python/PostgreSQL et 5 scénarios Chromium réussis ; Chromium contre API simulée, pas contre Qwen ou la base du PC.
- Aucun système utilisateur ou donnée de production modifié par cet audit.

## Note
- MVP éditorial privé : **7/10** ; génération et revue structurées, audit, données cloisonnées au niveau des requêtes, tests pertinents.
- Aptitude SaaS public multi-utilisateur : **2,5/10** ; rôles, identité, paiements, publication et conformité exploitation non livrés.
- Note de synthèse du logiciel au regard de la cible commerciale : **5/10**, non assimilable à un score CVSS.

## Constats (sévérité évaluée par rapport à la cible)
| ID | Sévérité | Catégorie | Fichier | Constat | Impact | Traitement |
| --- | --- | --- | --- | --- | --- | --- |
| SEC-001 | Majeure | Contrôle d'accès | apps/api/main.py | `/ai/generate` accepte les requêtes anonymes quand l'identité privée est absente, sans garde de boucle locale. | Une exposition accidentelle du port permet d'utiliser le modèle sans jeton. | Corrigé sur branche : accès anonyme exclusivement depuis client+Host boucle locale. |
| SEC-002 | Majeure | Disponibilité | apps/api/main.py, editorial/api.py | Pas de borne de requêtes LLM simultanées. | Saturation mémoire/CPU ou attente longue. | Corrigé : 2 places maximum par processus, HTTP 429 avant écriture de nouveau run, test de saturation. Un quota multi-instance reste à faire. |
| REL-002 | Majeure | Livraison/QA | scripts/deploy_local.py | La validation PC vérifiait API/Qwen sans tester HTML/JS, session web et lecture de bibliothèque. | Écran inutilisable malgré livraison marquée réussie. | Corrigé : garde live Studio avant et après bascule, mot de passe privé distinct obligatoire, retour arrière existant. |
| IAM-001 | Bloquante SaaS | RBAC | editorial/api.py, apps/api/studio.py | Un seul tenant/acteur configurés par variables serveur ; aucun compte ni rôle admin/rédacteur en chef/rédacteur/relecteur. | Impossible de déléguer les droits ou attribuer correctement les actions en SaaS. | Construire IdP, membres, permissions server-side et tests de refus. Ne pas fabriquer des rôles uniquement en frontend. |
| TEN-001 | Majeure SaaS | Multi-tenant | editorial/store.py | Requêtes actuelles filtrées par tenant, mais absence de sessions tenant-aware et d'administration des appartenances. | Pas d'isolation SaaS exploitable par comptes multiples. | Association utilisateur↔tenant en DB, sélection vérifiée côté serveur, RLS DB en défense en profondeur avant commercialisation. |
| PRIV-001 | Majeure SaaS | RGPD | editorial/store.py, pilotage/migration.sql | Conservation durable des prompts, sorties exactes, décisions et audits, sans politique d'effacement/rétention prouvée. | Risque de conservation excessive de données personnelles et de demandes RGPD impossibles à satisfaire. | Inventaire, durées, effacement/anonymisation compatible intégrité de l'audit, export, registre, DPA/sous-traitants. |
| BILL-001 | Bloquante SaaS | Paiement | absent | Aucun abonnement, essai, upgrade/downgrade, webhook signé, idempotence de facturation ni résiliation. | Commercialisation impossible. | Définir offres et provider, états et événements serveur, tests webhooks dupliqués/hors ordre. |
| EDIT-001 | Bloquante publication | Workflow | editorial/store.py | Workflow réel = génération → attente de validation → approved ; pas de publication, programmation, calendrier, embargo ni droits CMS. | Un « approved » ne peut pas être assimilé à « publié ». | Modèle explicite brouillon→relecture→approuvé→programmé→publié, rôles et journal d'événements. |
| EDIT-002 | Modérée | Édition | apps/web/studio.js | Révision uniquement par JSON structuré ; verrouillage global `expected_revision` mais pas de merge collaboratif. | UX technique, conflits difficiles à arbitrer à plusieurs. | Éditeur de champs structurés et diff de versions ; conserver vérification transactionnelle serveur. |
| MEDIA-001 | Non implémenté | Médias | apps/web, editorial | Pas d'upload, transcodage, stockage objet ni antivirus ; uniquement `image_prompt`. | Chaîne vidéo incomplète. | Spécifier ingestion puis isoler stockage, quotas, MIME réel, virus, ACL, liens expirants. |
| PERF-001 | Modérée | PostgreSQL | editorial/store.py, pilotage/migration.sql | Tri/filtre du catalogue via champs JSONB sans index adapté ; historique également filtré sur JSONB. | Scans et tris coûteux lorsque le nombre d'histoires augmente. | EXPLAIN ANALYZE avec volumes réalistes, index expression/partiels après migration revue, puis tests de pagination. |
| PERF-002 | Non mesurée | Frontend | apps/web/studio.js, studio.css | Pas de rapport Lighthouse ou mesure INP/LCP/CLS réelle ; bundles sans framework légers. | Performance vécue non qualifiée. | Mesurer sur appareil modeste, réseau lent et jeu de données significatif avant optimisation. |
| A11Y-001 | Modérée | WCAG 2.2 AA | apps/web/studio.css | Plusieurs textes secondaires initialement sous 4,5:1, focus visuel peu contrasté. | Lecture et navigation dégradées. | Correctif ciblé des couleurs et focus ; contrôle navigateur additionnel, audit WCAG complet restant. |
| A11Y-002 | Modérée | WCAG 2.2 AA | apps/web/studio.html, studio.js | Onglets sans lien explicite vers panneau, absence navigation Home/End, dialogues sans libellés ARIA. | Difficulté lecteur d'écran/clavier. | Correctif sémantique + test navigateur. |
| SEC-003 | Modérée | Supply chain | requirements.txt, .github/workflows | Versions directes figées mais pas de verrouillage transitif, ni audit CVE automatisé initialement. | Vulnérabilité transitive non détectée en CI. | Workflow `pip-audit` ajouté, résultats à vérifier ; politique de mise à jour et lock/ hashes à prévoir. |
| SEC-004 | Modérée | Configuration | compose.yml | Identifiants de démonstration PostgreSQL/MinIO en clair ; ports localhost uniquement. | Faible en dev local, dangereux si config copiée vers un serveur accessible. | Ne pas réutiliser ces identifiants en production ; secrets hors Git, fichiers Compose séparés, TLS/ACL. |
| OPS-001 | Modérée SaaS | Sessions/limites | apps/api/studio.py | Sessions et anti-bruteforce en mémoire d'un seul worker et indexés par IP de connexion. | Non distribué, peut mal fonctionner derrière proxy multi-usagers. | Session partagée/rotation sécurisée, stratégie trusted proxy, rate limiting durable avant exposition publique. |
| AI-001 | Modérée | Fiabilité éditoriale | editorial/service.py | Sources et réponses Qwen non vérifiées automatiquement, protection prompt-injection seulement instructionnelle. | Hallucinations et confusion faits/légendes. | Références sourcées, revue factuelle et interdiction de publication automatique sans acceptation humaine. |
| QA-001 | Majeure de recette | Tests réels | browser_checks/test_studio_browser.py | Les cinq tests E2E utilisent une API simulée ; pas de Lighthouse/axe automatisé ou parcours navigateur sur la DB/LLM du PC. | Succès CI insuffisant pour accepter la livraison utilisateur. | Recette PC privée, sans secrets dans les logs, résultat par SHA et profils mobile/desktop. |
| SEO-001 | Hors périmètre privé | SEO | apps/web/studio.html | Espace privé sans page publique indexable ; pas de stratégie SEO. | Aucun impact SEO sur l'atelier privé ; enjeu seulement pour futur site public. | Créer un site vitrine séparé avec métadonnées, robots/sitemap et pages publiques autorisées. |

## OWASP Top 10 — situation
- A01 Broken Access Control : cloisonnement tenant dans les requêtes existantes; IAM/RBAC manquants pour une commercialisation.
- A02 Cryptographic Failures : cookie HttpOnly, SameSite Strict et HTTPS requis à distance; rotation, chiffrement et sauvegardes à vérifier.
- A03 Injection : requêtes psycopg paramétrées; le frontend emploie `textContent`, pas d'éditeur HTML libre. Pas d'exploitation SQL/XSS prouvée.
- A04 Insecure Design : génération concurrente non bornée avant correctif; états publication/paiement/quotas non conçus.
- A05 Security Misconfiguration : bootstrap LLM anonyme auparavant exposable, identifiants Compose locaux de test.
- A06 Vulnerable/Outdated Components : audit transitoire via `pip-audit`, CVE et dépendances transitives à suivre.
- A07 Identification/Authentication Failures : mot de passe Studio privé, pas de comptes/SSO/MFA, anti-bruteforce mono-processus.
- A08 Software and Data Integrity : code SHA/CI/rollback; actions externes à SHA figé, mais revue de la chaîne CI indispensable.
- A09 Logging & Monitoring : audit/outbox atomiques ; alertes d'exploitation, métriques et procédures d'incident incomplètes.
- A10 SSRF : base Qwen donnée par configuration serveur ; aucune URL arbitraire issue de l'utilisateur dans le chemin IA constaté.

## Points positifs
- Validation Pydantic stricte, séparation transport/model/store, SQL paramétré.
- Idempotence de génération, contrôles contre sorties Qwen tronquées/JSON non conforme.
- Relecture humaine explicite, versions et historique auditables, conflits de version détectés.
- Pas de HTML libre ni injection `innerHTML` dans le rendu des textes.
- Pagination isolée par tenant, tests PostgreSQL sur base jetable.
- CI sur SHA, installation candidate et rollback en cas d'échec, pas de publication automatique.
- Bundles web statiques modestes; UI responsive en français.

## Recette manuelle encore obligatoire
1. Installation PC avec identité et secret Studio distincts : HTML/assets, session, logout, tests sur HTTPS avec proxy si accès mobile.
2. Création vraie histoire, test Qwen réel (2 étapes complètes ou erreur explicite) et contrôle des traces PostgreSQL.
3. Rejet, révision d'analyse invalidant le storyboard, révision de storyboard, acceptation des deux sorties, refus après approbation.
4. Plusieurs onglets simultanés sur le même run, conflits 409, interruption en cours d'appel modèle, redémarrage du service.
5. Requête autre tenant et requêtes sans authentification ; échec verrouillé avant exposition réseau.
6. Tests lecteurs d'écran, focus, zoom 200/400 %, clavier seul, contraste de tous les états ; audits Lighthouse/axe.
7. Sauvegarde/restauration réelle d'une base **isolée**, contrôle de provenance, rollback de release; aucun effacement de données réelles.

## Décision
**Go pour poursuivre l'atelier privé après CI et recette PC réelle; No-Go pour commercialisation SaaS publique.**
La fusion de correctifs n'autorise pas à déclarer le PC installé ou la recette client acceptée.
