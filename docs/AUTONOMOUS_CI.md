# CI-002 — Revue automatique, triage des échecs et dossier de release

État : code proposé en PR ; **ne signifie pas qu'un agent IA corrige déjà
tout le code ou que le PC reçoit automatiquement les releases**.

## Chaîne et frontières de confiance

1. **Sur chaque PR** : `.github/workflows/regression.yml` réalise les tests
   Python, les contrôles syntaxiques et les essais PostgreSQL **jetables**.
   `.github/workflows/ci-risk-review.yml` fait l'inventaire déterministe
   des chemins modifiés : risque de secret versionné (**bloquant**), migration
   à approuver, changement de CD, dépendance, absence de test ou de documentation.
   L'outil indique des **pistes de revue**, jamais une approbation humaine.
2. **Sécurité des dépendances** : `.github/workflows/security-deps.yml` lance
   `pip-audit` sur **toutes les PR**, chaque push sur `main`, manuellement
   et de façon hebdomadaire (lundi 06:17 UTC). Il peut échouer pour une
   vulnérabilité. **Aucune mise à jour automatique des dépendances** n'est
   effectuée : elle doit être revue, testée et livrée avec le reste.
3. **Après une CI** : `.github/workflows/ci-status-report.yml` reçoit un
   événement `workflow_run` pour Full regression, Dependency security audit
   et Studio browser journeys. Sur une PR du même dépôt, si le SHA est encore
   celui de la PR et que l'échec est avéré, un commentaire bot **dédupliqué**
   décrit le type de défaut et la marche à suivre. Un nouveau résultat du
   même workflow met le commentaire existant à jour ; pas de publication de
   prompts, sorties Qwen ni logs d'exception. **Cela ne modifie pas le code.**
4. **Après une CI de `main`** : le même reporting écrit dans le résumé
   GitHub Actions un **dossier préparatoire** indiquant SHA, réussite/échec
   de cette CI, état affiché du flag local, contrôles distincts à vérifier,
   prérequis de la MEP et rollback. **Le résumé ne certifie pas** les autres
   CI et ne constitue ni une livraison ni une approbation du produit.

La correction réellement autonome des régressions Python nécessite un agent
de développement authentifié, limité à **une branche de travail**, capable
de reproduire la panne, proposer un diff minimal, exécuter les tests et
créer/mettre à jour une PR. **Aucun agent avec accès en écriture n'est démarré
par les workflows de cette livraison.** Une erreur CI génère du triage, pas
une modification forcée ni une série de retries. Pour enclencher une boucle
d'agent, fournir et vérifier explicitement la connexion Codex/permissions,
les limites de tentatives et les garde-fous ; ne jamais donner des secrets
de production à du code de PR.

## Isolation et permissions

| Workflow | Code exécuté | GitHub permissions | Effet |
| --- | --- | --- | --- |
| Full regression | code de la PR ou main | `contents:read` | Tests ; aucune MEP |
| Automated PR risk review | code de la PR | `contents:read` | Diagnostic statique non mutateur |
| Dependency security audit | code de la PR ou main | `contents:read` | Détection CVE |
| Automated CI triage and release evidence | **main de confiance uniquement** | `contents:read, actions:read, pull-requests:read, issues:write` | Mise à jour d'un commentaire bot CI ou résumé release |
| Private PC delivery | SHA de `main` autorisé | `contents:read` | Installer **uniquement** après autorisation SHA exact et flag ON |

Le token à écriture limité du rapport de CI **ne doit jamais exécuter le
code des PR**. Le script vérifie le dépôt d'origine et le SHA actuel
avant publication. Si l'association à la PR est ambiguë ou obsolète,
il n'écrit pas. Les données du run sont réduites aux identifiants et statuts
des jobs, sans ingestion des logs ni commandes injectées.

Le commentaire GitHub n'est pas une vraie `APPROVE`, ni un verdict de revue
sémantique. La protection de branche (required checks/reviews) n'est pas
modifiée par cette PR ; elle doit être configurée séparément selon les droits
du dépôt. Les contrôles de risque heuristiques ne garantissent pas la
détection de tous les secrets ou défauts.

## Vérification et maintenance

Depuis un checkout Linux :

```bash
python -m unittest tests.test_ci_autonomy tests.test_ci_status_report -v
python scripts/run_regression.py
python scripts/ci_autonomy.py --base origin/main --head HEAD
```

Le test PostgreSQL de CI ne doit pas être exécuté sur la base PC :
`PO_TEST_DATABASE_URL` est réservé à la DB jetable et
`PO_ALLOW_TEST_MIGRATION=yes` la rend explicitement modifiable.
Sur GitHub, vérifier les jobs **Full regression**, **Automated PR risk
review** et **Dependency security audit** au SHA de la PR.

Après fusion, observer **le premier vrai événement workflow_run** avant
d'affirmer que le reporting auto fonctionne. Vérifier que le job de reporting
est exécuté et que ses permissions peuvent modifier un commentaire bot
uniquement dans les cas prévus. Sur une PR, provoquer un échec **dans une
branche de test isolée** (pas dans `main`), puis valider le message et sa
mise à jour après correction ; ne pas provoquer un incident production.

Pour un rapport d'échec : identifier premier test réellement cassé, vérifier
version des dépendances/variables de CI, reproduire dans un environnement
jetable, écrire un test de non-régression et un patch révisable sur branche
séparée. Maximum trois tentatives de correction avant signalement, pas de
rejouabilité automatique de génération Qwen à résultat incertain.

Pour préparer une livraison : se baser sur le **SHA final de `main`**,
CI et audit de dépendances au même SHA, preuve d'approbation humaine de ce
SHA, sauvegarde/restauration adaptée si migration, et recette PC réelle.
`LOCAL_PC_ENABLED=false` doit rester la valeur par défaut ; la livraison
est un workflow distinct qui demeure soumis à autorisation.

## Rollback

Si le rapport automatique gêne la revue : désactiver uniquement le workflow
`Automated CI triage and release evidence` dans GitHub Actions ou réverter
sa PR. Les commentaires déjà publiés sont des métadonnées, pas des données
métier. Si la revue automatique remonte des faux positifs, ajuster ses tests
puis la règle dans une nouvelle PR ; **ne jamais désactiver les tests métier
pour obtenir une CI verte**.

Cet incrément n'introduit ni migration, ni worker PC, ni secret supplémentaire,
ni modification du déploiement local. La CI ne remplace pas la recette sur
Ubuntu WSL et Qwen/Vulkan réel.

## Journal de qualification

- 15/10/2026 : conception et tests proposés sur branche CI-002. Les SHA,
  IDs de runs et résultats seront consignés dans la PR après vraie exécution.
- Le prochain merge `main` ne vaut pas acceptation du produit ni Go MEP.


## OPS-CI-WARN — avertissements même sur CI verte

Voir [CI_WARNING_MONITORING.md](CI_WARNING_MONITORING.md) : surveillance des
annotations GitHub Checks, Issues dédupliquées, politique de SHA épinglés,
Dependabot. La création d'une Issue ne prouve ni CVE ni notification email.
Aucun nouvel accord de fusion ou de MEP ne résulte de ce contrôle.
