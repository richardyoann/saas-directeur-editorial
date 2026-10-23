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

## Bac à sable Docker : préparation opérationnelle (22/10/2026)

Fichiers livrés : ci/local/Dockerfile, ci/local/requirements-ci.txt, scripts/arvor_ci_sandbox.py, scripts/arvor_ci_entrypoint.sh et tests/test_arvor_ci_sandbox.py.

Le Dockerfile est basé sur PostgreSQL 16 et prévoit Python 3.12/3.14, Chromium, FFmpeg, Node, Playwright, Gitleaks 8.28.0 vérifié par SHA256 et pip-audit. Il reste à construire et tester sur une machine Docker opérationnelle.

### Préparation sur WSL, sans déploiement applicatif

Après revue et épinglage du commit de la branche CI dans une copie fiable :

    docker build -f ci/local/Dockerfile -t arvor-ci:review .
    docker image inspect --format '{{.Id}}' arvor-ci:review

Utiliser l'identifiant sha256 immuable retourné, jamais seulement un tag Docker. Préparer un clone Git autonome et propre au SHA de la PR à tester, un dossier de code CI de confiance hors du clone (avec arvor_local_ci.py et arvor_ci_entrypoint.sh), et un dossier privé de preuves accessible à l'UID 999 du conteneur.

Simulation du lanceur, sans exécution de tests :

    python scripts/arvor_ci_sandbox.py --image-id "$IMAGE_ID" --checkout "$CANDIDATE_CLONE" --trusted "$TRUSTED_CONTROLLER" --evidence "$PRIVATE_EVIDENCE" --sha "$PR_HEAD_SHA" --base-sha "$PR_BASE_SHA" --pr "$PR_NUMBER"

Une fois l'image et la séparation des volumes/identités vérifiées, l'option --execute lance seulement les tests locaux dans un conteneur jetable, sans réseau, sans privilèges, sans socket Docker ni secrets et sans volumes métier. Elle n'installe pas Arvor.

Le cache pip-audit est préchargé au build et recopié en espace temporaire. Si l'audit hors ligne échoue, la gate échoue et l'attestation PASS est interdite.

### Critères bloquants restants

- 16 gates sont maintenant définies : 6 Python/Postgres/benchmark, 3 JS, 1 syntaxe Python, 1 navigateur, 1 dépendances, 1 Gitleaks, 1 policy, 1 revue de risques, 1 vidéo synthétique 75 s.
- La gate vidéo appelle scripts.smoke_video_75 : ce script est présent sur la PR #214 et absent du main actuel. L'absence doit produire un échec, jamais un PASS.
- Le signataire Ed25519 vérifie schéma et cohérence mais ne prouve pas, à lui seul, qu'un log reçu du sandbox est authentique : le superviseur extérieur au code candidat doit contrôler les logs, l'image, les commandes, les codes de retour et l'identité Git distante AVANT signature.
- Une réussite 75 s synthétique ne remplace pas les recettes Qwen réel, voix, GPU, ni la validation éditoriale.
- Aucun test sur l'image Docker complète n'a été lancé dans cet environnement, qui n'a pas de Docker et n'est pas le PC de l'utilisateur.
- Le workflow de notification GitHub/Slack n'est pas branché automatiquement à OpenCode et aucun webhook privé n'est configuré.
- Ne jamais considérer ARVOR_LOCAL_CI_FULL_PARITY_APPROVED comme une preuve d'isolation en soi. Le laisser désactivé avant certification.
- Aucun workflow GitHub Actions existant n'est encore désactivé; #214 reste en brouillon; aucun merge ni déploiement PC autorisé par cette préparation.

### Tests locaux de développement

Dans un environnement de test distinct, 16 tests unitaires ont passé (signature, fraude SHA, tests skipped, cache de publication, isolation du lanceur), ainsi que la compilation Python et la syntaxe shell. Cela ne constitue pas la recette complète de la CI sur Arvor.

## Incident de recette PC : cache pip-audit UID 999 (22 octobre 2026)

Preuve utilisateur : image Docker initiale `sha256:8dfa40b5b4a59157b3f85f0ef34597c468dba753b2245144605b019a32629353` avec PostgreSQL 16, Python 3.12/3.14, Chromium, FFmpeg, Gitleaks et Node vérifiés. Le lanceur `--execute` renvoyait `returncode: 1` avant toute gate : `cp -a /opt/arvor/audit-cache/. /tmp/audit-cache/` échouait avec `Permission denied`, puis aucun JSON dans `evidence`. Ce n'est pas une régression du projet.

Correction proposée dans la PR #215 : le Dockerfile termine le préchauffage de cache par `chown -R 999:999 /opt/arvor/audit-cache`; le point d'entrée exige un cache lisible puis emploie `cp -R`, sans conservation de la propriété du cache construit par root. Un test statique de non-régression vérifie les deux instructions. La correction n'est pas considérée comme validée tant que l'image n'a pas été reconstruite et testée sous WSL.

Depuis le clone `ci-source` non modifié localement :

    git fetch origin feat/OPS-LOCAL-CI-ATTEST-20261022
    git switch --detach FETCH_HEAD
    cp scripts/arvor_ci_entrypoint.sh "$HOME/arvor-ci-lab/trusted/"
    chmod 755 "$HOME/arvor-ci-lab/trusted/arvor_ci_entrypoint.sh"
    docker build -f ci/local/Dockerfile -t arvor-ci:review .
    docker image inspect --format '{{.Id}}' arvor-ci:review

Récupérer le **nouvel** ID d'image complet `sha256:...` et refaire le diagnostic de lecture/copie du cache dans un conteneur jetable UID 999. Les anciens IDs sont immuables et **ne sont pas corrigés** par le rebuild. N'effectuer ni fusion GitHub ni livraison PC pour ce diagnostic.


## Incident de recette PR #214 : simulateur vocal Piper (23 octobre 2026)

Preuves WSL : 390 tests Python 3.12 executes en 18 s; 3 failures et 1 error dans tests/test_voice_timeline.py. FFmpeg est disponible, mais la detection du simulateur Piper cree dans tempfile.TemporaryDirectory echoue : piper_or_ffmpeg_unavailable.

Modifications CI sur #215 :
- scripts/arvor_ci_sandbox.py : montage /tmp du seul conteneur en rw,exec,nosuid,nodev ; volumes metier et hote non modifies.
- scripts/arvor_ci_entrypoint.sh : prevalidation cree un petit executable temporaire puis le lance, pour echouer avec un diagnostic specifique si /tmp interdit les executions.
- scripts/arvor_local_ci.py : correction du verdict video_75, auparavant susceptible d'etre ecrase par un simple code de sortie 0; test negatif ajoute.
- Tests metier #214 inchanges, aucun skip accepte.

Pour retester : recuperer le nouveau SHA de #215, mettre a jour les deux fichiers externes arvor_ci_entrypoint.sh et arvor_local_ci.py dans trusted, executer les tests unitaires puis le sandbox --execute. L'image Docker SHA256 existante peut etre reutilisee, car aucun changement de Dockerfile dans cet incident. Cette correction doit etre confirmee par la recette reelle WSL.

Aucun merge #214, statut GitHub vert, publication Slack automatisee ni deploiement PC autorise par ce diagnostic.

## Incident navigateur Playwright sur WSL (23 octobre 2026)

Observations de la recette PR #214 : 390/390 Python 3.12 et 390/390 Python 3.14 sont OK, preparation PG, benchmarks SQL, 3 syntaxes JS et syntaxe Python sont OK (10/16 gates). Le controle browser a echoue avant execution des 18 parcours : setUpClass de StudioBrowserJourneys, Playwright 1.58.0 cherchait le binaire Chromium headless shell sous /tmp/.cache/ms-playwright/chromium_headless_shell-1208 alors que l'image avait seulement Debian Chromium installe par apt.

Correction dans la branche CI #215 :
- ci/local/Dockerfile utilise PLAYWRIGHT_BROWSERS_PATH=/opt/arvor/playwright-browsers et execute lors du build avec reseau disponible : /opt/arvor/py312/bin/python -m playwright install --with-deps --only-shell chromium. Les fichiers du navigateur sont lisibles par UID 999.
- scripts/arvor_local_ci.py transmet uniquement ce chemin aux sous-processus Python a travers la liste d'environnement limitee.
- scripts/arvor_ci_entrypoint.sh demarre Playwright Chromium headless avant le demarrage de PG et des tests; echec ferme si navigateur indisponible.
- scripts/arvor_ci_sandbox.py reserve un /dev/shm prive de 512 Mo sans utiliser --ipc=host et preserve --network=none, --read-only, --cap-drop=ALL, aucune credentielle.
- tests/test_arvor_ci_sandbox.py verifie les caracteristiques precedentes statiquement.

**Reconstruction requise :** contrairement au correctif tmpfs Piper, le Dockerfile change. L'ancien ID d'image ne contient PAS Chromium headless shell de Playwright. Recuperer le dernier SHA #215, construire docker build -f ci/local/Dockerfile -t arvor-ci:review . ; recuperer son nouvel ID sha256 puis recopier arvor_local_ci.py et arvor_ci_entrypoint.sh de la branche CI approuvee dans le dossier trusted.

Valider sous Docker --network=none et UID 999 que sync_playwright().start().chromium.launch(headless=True, args=['--no-sandbox']) fonctionne, puis relancer la CI --execute. Aucun succes global de 16 gates annonce a ce stade.

## Incident pip-audit hors reseau (23 octobre 2026)

Le rapport de PR #214 a valide les 11 premieres gates, dont les 18 parcours navigateur et 390 tests en Python 3.12 et 3.14. La gate dependencies echouait avec Failed to upgrade pip, wheel, setuptools dans /tmp : l'ancienne commande pip-audit -r requirements.txt tente une resolution avec pip alors que le conteneur n'a pas de reseau.

Sur CI #215, changement en audit local strict :
- docker build (avec reseau) lance /opt/arvor/py312/bin/python -m pip_audit --local --strict pour auditer l'environnement complet installe, outils et dependances transitives inclus, et preremplir le cache HTTP de vulnérabilites.
- controle sandbox (reseau interdit) lance pip-audit --local --strict avec le cache prechauffe, sans resolver pip, sans --fix, sans ignorer les vulnérabilites.
- le point d'entree refuse de tester un requirements.txt candidat demandant une dependance absente/differente de la liste directe installee dans l'image de confiance.
- ces modifications imposent une reconstruction de l'image Docker et un nouvel ID sha256. Il faut recopier arvor_local_ci.py et arvor_ci_entrypoint.sh depuis le dernier SHA CI #215.
- si le cache HTTP est indisponible ou expire, l'audit hors-ligne doit echouer ferme ; reconstruire l'image avec acces a la base de vulnerabilites et examiner les raisons avant toute approbation.

Ce mecanisme evalue les dependances au regard des avis disponibles lors de la construction de l'image ; il ne garantit pas leur fraicheur indefiniment. Les 16 portes restent obligatoires, sans skip, sans publication d'un resultat vert avant recette integre.

Aucune modification de la PR #214, des donnees metier, du PC Arvor ou des protections GitHub existantes.

## Blocage preflight inventaire (23 octobre 2026)

Le nouveau build de l'image était réussi. Sur le PC WSL : pip-audit --local --strict sans reseau a signale No known vulnerabilities found et 21 tests unitaires ont réussi. Cependant, avant les gates, la prevalidation a levé FileNotFoundError pour /tmp/arvor-requirements.txt. Cause : le script comparait les dépendances à un manifeste copié dans /tmp pendant le build, masqué à l'exécution par --tmpfs=/tmp.

Correctif PR #215 : verification preflight des pins exacts de /workspace/requirements.txt contre les distributions réellement installées, dans les deux environnements Python 3.12 et 3.14, via importlib.metadata + packaging.requirements. Controles explicites des extras demandés (ex: psycopg[binary]); refus des dépendances non épinglées, manquantes ou de versions différentes. Aucun telechargement, aucune ecriture source et aucune suppression d'audit.

Le Dockerfile est inchangé depuis le build de l'image qui a déjà passé pip-audit hors ligne. Image à réutiliser sans rebuild : sha256:ecc09ca2b26f007b940631a8ebcf3fa4b60a757114de2fa6567220637207a5b1. Actualiser la branche CI, recopier uniquement scripts/arvor_ci_entrypoint.sh dans le trusted, puis executer tests unitaires et sandbox --execute avec les SHA de la PR #214. Le correctif ne vaut pas recette réussie tant que les 16 portes ne sont pas toutes passées.