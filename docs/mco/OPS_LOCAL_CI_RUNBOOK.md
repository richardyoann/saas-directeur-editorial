# Arvor — CI locale OpenCode : runbook

**Statut : implémentation en PR #215, non activée.** Aucun lancement sur PC privé, aucun statut GitHub publié par ce travail, aucun webhook Slack configuré, aucun merge ni MEP.

## Architecture

- scripts/arvor_local_ci.py : collecte déterministe, matrice Python 3.12 et 3.14, PostgreSQL de test, syntaxe, navigateur, pip-audit, Gitleaks, politique et risques.
- scripts/arvor_ci_attestation.py : signature Ed25519 de la preuve liée au SHA, rejet de tests ignorés, manquants ou en échec.
- scripts/arvor_ci_publish.py : dry-run par défaut; validation de signature, date et HEAD/base de PR, statut GitHub externe facultatif puis notification webhook Slack privée.
- tests/test_arvor_local_ci.py : tests de sécurité et d'échec réseau simulé, sans publication réelle.

## Précondition de sécurité impérative

Le contrôleur **de confiance** doit être installé hors du checkout candidat depuis un commit relu et épinglé. Le code candidat doit être exécuté dans un conteneur ou une VM jetable non privilégié, sans secrets, sans volumes métier, sans socket Docker hôte et sans accès au runner de livraison editorial-pc.

ARVOR_CI_ISOLATED=1 est seulement un marqueur déclaratif. Ce n'est pas une preuve d'isolation. Un superviseur indépendant doit vérifier l'environnement, les logs, le digest de la politique et le SHA avant de signer. Ni le jeton GitHub, ni le webhook Slack, ni la clé privée ne doivent être montés dans le sandbox.

Préparer les dépendances épinglées avant l'exécution sans réseau du candidat. Le contrôle pip-audit doit disposer d'une base d'avis locale à jour ou d'une phase réseau strictement contrôlée.

## Exemple de commande dans une VM/conteneur déjà isolé

Pré-requis : environnement Python 3.12 et 3.14, Node, Gitleaks, Chromium, PostgreSQL 16 jetable sur port distinct, dépendances épinglées.

    export ARVOR_CI_ISOLATED=1
    export PO_TEST_DATABASE_URL="postgresql://po_test:ephemeral_ci_only@127.0.0.1:55483/po_test"
    export TRACE_TEST_DATABASE_URL="$PO_TEST_DATABASE_URL"
    export PO_ALLOW_TEST_MIGRATION=yes
    python -m scripts.arvor_local_ci \
      --checkout /sandbox/candidate \
      --sha "$PR_HEAD_SHA" --base-sha "$PR_BASE_SHA" --pr "$PR_NUMBER" \
      --python312 /opt/py312/bin/python --python314 /opt/py314/bin/python \
      --output /sandbox/evidence

Le reçu est non signé, confidentiel, en JSON; il contient les résultats, le SHA complet, des hashes des journaux privés et un run_id.

## Signature (service de confiance, hors sandbox)

Créer la clé privée **hors dépôt** avec permissions restrictives, par exemple :

    umask 077
    openssl genpkey -algorithm ED25519 -out /trusted-secrets/arvor-ci.key
    openssl pkey -in /trusted-secrets/arvor-ci.key -pubout -out /trusted-secrets/arvor-ci.pub

Après vérification indépendante de la preuve, transférer le reçu au signataire (sans exporter les logs ou les secrets). Exécuter les scripts de confiance depuis un répertoire hors checkout candidat :

    python -m scripts.arvor_ci_attestation sign \
      --input /trusted/incoming/RECU.json \
      --key /trusted-secrets/arvor-ci.key --key-id arvor-local-v1 \
      --output /trusted/signed/PREUVE.json
    python -m scripts.arvor_ci_publish \
      --attestation /trusted/signed/PREUVE.json \
      --public-key /trusted-secrets/arvor-ci.pub --key-id arvor-local-v1

Sans option publish, le mode reste une simulation et ne touche pas au réseau.

## Activation future de la publication

Configurer dans le processus de publication externe, jamais dans le dépôt ou le checkout candidat :

- ARVOR_GITHUB_STATUS_TOKEN : jeton à privilèges minimaux pour lire la PR et écrire les commit statuses.
- ARVOR_SLACK_WEBHOOK_URL : URL du webhook Slack privé du destinataire cible, sur hooks.slack.com.
- Clé publique épinglée et dossier d'anti-rejeu privé.

La publication est également **bloquée par défaut** : le superviseur de confiance doit définir ARVOR_LOCAL_CI_FULL_PARITY_APPROVED=true seulement après les contrôles d'isolation et de parité 7/7. Ne pas définir cette variable pour contourner la recette.

Après recette et approbation du mécanisme de publication :

    python -m scripts.arvor_ci_publish \
      --attestation /trusted/signed/PREUVE.json \
      --public-key /trusted-secrets/arvor-ci.pub --key-id arvor-local-v1 \
      --sent-dir /trusted/state/arvor-ci --publish

La publication viserait le contexte GitHub externe arvor/local-ci-attested au SHA exact. Slack recevrait un CR minimal : OK/KO, PR, SHA, gates et lien. Aucun jeton, prompt, média ou log détaillé n'y serait envoyé.

Un statut PASS, même authentifié, **ne constitue pas une autorisation de fusion ni de MEP**. Sans protection de branche disponible sur ce dépôt privé, le contrôle humain reste indispensable.

## Points restant avant migration complète

1. Vérifier et installer l'environnement d'exécution isolé et l'orchestrateur fiable. Aucun déploiement de cette CI sur ton PC n'a été fait.
2. Épingler les scripts/politiques hors checkout candidat et protéger la signature par un superviseur indépendant. Une simple variable d'environnement ne suffit pas.
3. Compléter les gates manquantes pour parité totale : deux fichiers JS supplémentaires et test vidéo 75 secondes de la PR #214.
4. Exécuter la vraie matrice Python 3.12/3.14, PostgreSQL 16, Chromium et audit sur une PR témoin. Treize tests unitaires du prototype ont été exécutés dans un environnement de développement séparé ; ce n'est pas la recette Arvor.
5. Configurer et tester GitHub status + webhook Slack réel, y compris les pannes Slack/GitHub, l'anti-rejeu et la modification de HEAD.
6. Après validation humaine, proposer une PR distincte de neutralisation des déclencheurs GitHub Actions redondants. Conserver les mécanismes de livraison PC verrouillés.
7. Conserver la PR #214 en brouillon; aucune fusion et aucune MEP sans accord dédié sur SHA complet.

## Commande de tests du module

    python -m unittest tests.test_arvor_local_ci -v
