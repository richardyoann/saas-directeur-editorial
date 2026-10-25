# OPS-LOCAL-CI — Préparation de migration OpenCode (22/10/2026)

Statut : **migration non activée**. Vérification le 25/10/2026 sur main
`d08fe0afe62f0ea209da239aeade0bd5f042d30d`, PR #214 `a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9`,
PR #215 `4751917560605009a20b673595448d200dc899be`. Aucun workflow n'a été
désactivé, aucun statut local n'a été publié, aucun merge ni déploiement.

## Inventaire de consommation et correspondance

L'arbre `main` contient 10 workflows YAML; l'API GitHub annonce 13 workflows
actifs, dont `pilotage.yml` et `video-75-acceptance.yml` qui ne sont pas présents
dans l'arbre `main` consulté, plus l'entrée dynamique Dependabot. Les 100 runs
les plus récents visibles (24–25/10) sont tous `failure` ou `skipped` : les
jobs de contrôle sont refusés avant exécution pour le problème de facturation/
limite de dépense. Le relevé de minutes n'est pas accessible : l'API de
facturation retourne 404 et réclame le scope GitHub `user`; aucun scope n'a été
ajouté et aucune dépense/plafond n'a été engagé.

| Workflow GitHub | Déclencheurs / runner | Remplacement local envisagé | Preuve et état |
| --- | --- | --- | --- |
| `regression.yml` — Full regression | PR, push `main`, manuel; `ubuntu-24.04`, matrice Python 3.12/3.14 + PostgreSQL 16 | `regression_312/314`, `db_prepare`, `sql_benchmark`, syntaxes dans les 16 gates supervisées | Reçu #214 historique 16/16 sans provenance; recette actuelle bloquée avant gates. Pas de parité acceptée. |
| `studio-browser.yml` — navigateur | PR filtrées sur Studio/tests, manuel; `ubuntu-24.04` | gate `browser` Playwright/Chromium | Historique seulement; pas de preuve indépendante récente. |
| `ci-risk-review.yml` — analyse déterministe des risques | PR vers `main`, manuel; `ubuntu-24.04` | gate `risk_review` et tests de l'inventaire | Pas de run local qualifiant le SHA courant. |
| `ci-policy.yml` — règles supply-chain | PR, push `main`, quotidien 05:43 UTC, manuel; `ubuntu-24.04` | gate `supply_chain` / politique épinglée | Run planifié et PR visibles en échec pré-exécution; remplacement non actif. |
| `secret-scan.yml` — Gitleaks | PR, push `main`, quotidien 04:19 UTC, manuel; `ubuntu-24.04` | gate `secrets` | Run planifié et PR visibles en échec pré-exécution; remplacement non actif. |
| `security-deps.yml` — dépendances | PR vers `main`, push `main`, lundi 06:17 UTC, manuel; `ubuntu-24.04` | gate `dependencies`, audit frais de l'image locale | Audit de build local récent `OK`; la gate candidate n'a pas tourné. |
| `ci-annotations.yml` — watcher incidents | `workflow_run` de workflows CI/livraison, quotidien 07:07 UTC, manuel; `ubuntu-24.04` | Aucun remplacement d'annotations/issues prouvé | 51 runs `workflow_run` parmi les 100 derniers; échec pré-exécution. Cascade redondante à supprimer après bascule. |
| `ci-status-report.yml` — triage et preuve release | `workflow_run` regression/dépendances/navigateur; `ubuntu-24.04` | Publisher local GitHub/Slack prévu | 12 runs `workflow_run` parmi les 100 derniers; pas de publication réelle. Le publisher ne remplace pas encore le triage d'issues. |
| `local-delivery.yml` — livraison PC | `workflow_run` succès de regression sur push `main`, manuel; runner auto-hébergé `editorial-pc` | Orchestration OpenCode locale à concevoir | 6 runs observés `skipped`; garder actif jusqu'au remplacement testé. Vérification `LOCAL_PC_ENABLED` et SHA exact conservée. |
| `chat-approved-delivery.yml` — livraison approuvée | création de branche `delivery-approved/*`; Ubuntu de validation puis `editorial-pc` | Orchestration locale à concevoir | Un run observé `skipped`; voie distincte de livraison. Garder active et fail-closed. |

L'API d'exécutions expose aussi deux définitions historiques actives absentes de
`main` (`pilotage.yml`, `video-75-acceptance.yml`). Leur présence d'API ne prouve
pas qu'elles consomment actuellement des minutes; vérifier l'historique et leur
usage avant de les désactiver. Les quatre tâches planifiées exactes ci-dessus
sont toujours configurées. Les deux workflows de livraison ne sont pas des
doublons de tests et restent protégés.

## Blocages de bascule constatés

- `opencode` est absent (`command not found`) dans l'environnement de cette
  session;
  aucune commande `/arvor-ci` n'est installée ni testable ici. Le script existant
  `scripts/qualify_arvor_ci_wsl.sh` ne cible que la recette #214 et refuse
  correctement son changement de workflow protégé.
- Le contrôleur #215 et son publisher ne sont pas fusionnés ni validés par une
  revue indépendante. Il n'y a aucun statut local réel publié.
- `GET /branches/main/protection` répond HTTP 403 : GitHub indique qu'un plan
  Pro ou un dépôt public est nécessaire. Le dépôt doit rester privé. Il est donc
  impossible de confirmer/configurer ici les statuts requis; ne pas retirer les
  contrôles hébergés.
- Aucun fichier de clé Ed25519 n'est configuré dans le lab consulté. Ne pas
  créer ni utiliser une clé tant qu'une preuve de recette valide et un chemin
  sécurisé hors dépôt/conteneur ne sont pas disponibles.
- Aucun déclencheur hébergé n'a été arrêté. Les runs visibles échouent avant
  démarrage; le montant réellement facturé demeure inconnu. Le propriétaire
  doit consulter l'onglet GitHub Actions de la facturation avec son accès UI,
  sans augmenter le plafond ni changer le caractère privé du dépôt.

## Objectif
Exécuter les contrôles coûteux localement, en isolation, sans confondre exécution OpenCode et preuve indépendante. GitHub conserve PR, commits et statuts externes; Slack reçoit un CR métadonnées seulement.

## Contrôles obligatoires
1. Vérifier HEAD == SHA complet de la PR distante, checkout propre et commit immuable.
2. Exécuter le code candidat dans un conteneur/VM éphémère sans secrets, sans réseau vers les services privés, sans accès au socket Docker hôte, aux volumes métier ni au runner de livraison.
3. Reproduire la matrice Python 3.12/3.14, PostgreSQL 16 jetable, régression sans skip, benchmarks SQL, syntaxe JS, 18 parcours navigateur, pip-audit, Gitleaks, politique supply-chain, tests vidéo 75 s lorsqu'ils existent.
4. Produire une attestation JSON par SHA (version du plan, environnement, commandes, codes de retour, compteurs, durée, hashes des artefacts), signée par un service de confiance hors checkout. Un échec, skip, preuve manquante ou SHA changé interdit PASS.
5. Le service de publication, distinct du candidat, revalide la tête distante avant d'envoyer un statut GitHub. Ne jamais laisser le code testé accéder au token de publication ou à la clé de signature.
6. Slack : un message de fin OK/KO par exécution, lien PR, SHA, gates, erreurs catégorisées, prochaine action; aucun prompt, jeton, log brut ou donnée métier.
7. Revue humaine obligatoire avant fusion. Fusion et livraison PC sont des opérations séparées; SHA exact approuvé pour chaque livraison.

## Migration progressive
- Phase A : scripts et tests unitaires du contrôleur, exécution en mode shadow, comparaison aux anciens workflows.
- Phase B : publication de statuts externes et CR Slack après preuve sur PR témoin, avec déduplication et contrôle des erreurs réseau.
- Phase C : valider la politique de fusion et les droits GitHub (sur dépôt privé, la protection native peut nécessiter une offre adaptée).
- Phase D : seulement après validation explicite, réduire les déclenchements automatiques GitHub Actions; conserver le workflow de livraison PC verrouillé et un diagnostic manuel.

## État connu
- PR #214 ouverte, non brouillon : ne pas fusionner sans gates et revue valides.
- Les runners GitHub hébergés refusent le démarrage pour paiement ou plafond de dépenses; ce problème n'est pas résolu par la migration.
- LOCAL_PC_ENABLED et LOCAL_PC_APPROVED_SHA : ne pas modifier.
- Aucun statut vert ne peut être émis à partir d'un simple texte OpenCode.
- Les anciens workflows ne doivent pas être désactivés dans cette PR de préparation.

## Critères de recette
- Tests négatifs : SHA falsifié, suite ignorée, gate absente, signature invalide, PR mise à jour pendant les tests, tentative de fuite de secret, Slack indisponible.
- Vérification d'une PR témoin complète sur les deux versions Python, avec PostgreSQL isolé.
- Comparaison des résultats locaux et des résultats GitHub lorsque les runners sont de nouveau accessibles.
- Validation humaine du modèle de confiance avant bascule.

## Modèle de confiance à implémenter
- La liste des gates et leurs versions provient d'une politique approuvée et épinglée hors du checkout candidat. Une PR ne peut ni retirer une gate, ni assouplir un seuil, ni substituer une commande tout en conservant un statut vert.
- La préparation des dépendances utilise des versions verrouillées dans une phase séparée; l'exécution du candidat est ensuite hors ligne, sans secrets, sans socket Docker hôte et sans montage des données métier.
- L'attestation contient au minimum dépôt, numéro de PR, SHA de tête et de base complets, identifiant d'exécution non réutilisable, horodatages début/fin, version de politique, gates attendues/exécutées, commandes normalisées, codes de retour, compteurs de tests et hashes des artefacts.
- Le JSON est sérialisé canoniquement avant signature. La signature asymétrique, son algorithme, l'identifiant de clé et la clé publique épinglée sont vérifiés par le service de publication; la clé privée reste hors du checkout, du conteneur testé et des logs.
- Le service de publication refuse une attestation expirée, rejouée, liée à un autre dépôt/PR/SHA, incomplète ou signée par une clé inconnue. Il relit le HEAD distant juste avant publication et publie `failure` ou aucun statut si le SHA a changé.
- Les contextes de statut sont fixes et documentés. Tant que `main` n'est pas protégé par un ruleset ou une règle équivalente, ces statuts restent informatifs et ne constituent pas une barrière technique de fusion.
- Les journaux détaillés restent dans un stockage privé à rétention bornée avec filtrage des secrets; Slack ne reçoit que les métadonnées prévues et un identifiant de preuve.

## Critères d'échec supplémentaires
- Politique de gates absente, modifiée par le candidat ou version non approuvée.
- Attestation périmée, rejouée, non canonique, d'un autre dépôt/PR/base/HEAD, ou clé révoquée/inconnue.
- Dépendance non verrouillée, accès réseau imprévu pendant l'exécution, montage d'un volume métier ou accès au socket Docker hôte.
- Publication impossible ou HEAD distant modifié entre la recette et l'envoi du statut.
- Absence de protection de branche : aucune automatisation ne doit alors interpréter le statut local comme autorisation de fusion.


## Mise à jour du modèle de provenance — 25 octobre 2026

Le format opérationnel est désormais le reçu hôte `arvor-local-ci-v1` plus un
journal hôte distinct `arvor-host-observation-v1`. Le vérificateur recalcule la
politique depuis le checkout contrôleur propre et épinglé, valide l'inspection
Docker structurée, l'image immutable, le code de sortie host-observed et le
hash de chaque gate/log. Il ne déduit aucune provenance d'un booléen du reçu ni
d'une variable d'environnement. Le signer utilise l'objet déjà validé et signe
le reçu avec la provenance vérifiée. Le publisher exige l'enveloppe signée,
compare les pins, vérifie l'état distant deux fois autour du status POST et
réconcilie un status ambigu avec l'URL unique du run. Les notifications Slack
ambiguës sont suspendues en `pending` et demandent une vérification manuelle
avant une nouvelle tentative.

Le superviseur bloque toujours par `CONTROL_PLANE_REVIEW_REQUIRED` toute PR
qui modifie le contrôleur, l'image, les workflows GitHub, `AGENTS.md` ou la
politique/runbook local CI. Cette PR #215 est une PR de contrôle : elle doit
être revue et qualifiée depuis un checkout approuvé séparé, sur un candidat
métier distinct (notamment #214), avec une nouvelle recette WSL au SHA final.
Aucune auto-approbation ni assouplissement du garde n'est accepté.

État au commit contrôleur `989a202f30e4525efff737ebcf55c197973c41d8` : 77 tests
contrôleur ciblés passent et l'image auditée fraîche est construite. La recette
exacte-SHA s'arrête avant les gates avec `CONTROL_PLANE_REVIEW_REQUIRED`, car
#214 modifie le workflow vidéo protégé. Aucun contournement, signature,
publication de statut ou notification d'attestation n'a été effectué; un message
Slack de clôture purement informatif a été publié. Le reçu historique des 16 gates
(`7c73cd…` contrôlant `a4f885…`) ne prouve pas la provenance indépendante. Voir
le résultat et les identifiants complets dans `OPS_LOCAL_CI_RUNBOOK.md`.
Revue finale, qualification distincte, checks GitHub démarrés et vérification
des règles de fusion restent bloquants.

La mise à jour d'inventaire du 25/10 est ci-dessus. Elle sert également de
critères d'acceptation/passation en l'absence d'un PRD CI distinct versionné.
