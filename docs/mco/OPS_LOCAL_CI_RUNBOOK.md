# Arvor — CI locale OpenCode : runbook

## 25 octobre 2026 — Refus de privilèges et volumes Docker inattendus

Le superviseur de la PR #215 contrôle maintenant en plus des restrictions existantes :
capabilities ajoutées, périphériques exposés, ports publiés, espaces PID/IPC
de l'hôte, options `seccomp=unconfined`/`apparmor=unconfined` et tout
volume ou montage étranger aux deux binds en lecture seule et aux trois
`tmpfs` prévus. Toute divergence retourne un échec bloquant avant les gates.

Validation de développement hors PC : syntaxe Python et dix cas isolés de
`inspect_isolation` réussis. Les deux nouveaux tests de régression sont
committés mais **la suite complète et la vérification de Docker inspect
sur WSL restent à exécuter au SHA final**. Ce durcissement ne certifie
ni la provenance indépendante ni la signature, ne publie aucun statut,
ne fusionne aucune PR et ne livre rien sur le PC.


## 24 octobre 2026 — Qualification WSL reproductible, sans fusion ni livraison

Le script `scripts/qualify_arvor_ci_wsl.sh` regroupe la recette du contrôleur
actuellement relu. Il ne modifie aucun checkout et refuse un SHA incomplet,
une branche sale, une base non ancêtre, un moteur Docker indisponible, un audit
périmé ou un contrôle KO. Il crée deux répertoires neufs sous
`$HOME/arvor-ci-lab` pour la politique en lecture seule et les preuves hôte ;
il ne réutilise pas les précédentes preuves.

Après revue indépendante et positionnement du checkout `ci-source` sur le
**SHA complet approuvé** de la PR #215, et du checkout `pr214` sur
`a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9` :

```bash
cd "${HOME}/arvor-ci-lab/ci-source"
bash scripts/qualify_arvor_ci_wsl.sh \
  CONTROLLER_SHA_COMPLET_APPRouve \
  a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9 \
  d08fe0afe62f0ea209da239aeade0bd5f042d30d
```

La commande exécute les tests du contrôleur, reconstruit une image Docker
avec `SECURITY_AUDIT_REFRESH` neuf, épingle son ID SHA256, lance les 16
gates individuellement et vérifie les 16 empreintes de logs. Elle conserve
les preuves en cas d'échec et ne produit aucune signature ni statut GitHub.
La provenance indépendante reste non certifiée tant qu'une revue/recette
de confiance séparée n'a pas eu lieu.

**Validation disponible avant WSL :** sept tests passent (syntaxe, mauvais SHA,
laboratoire absent, checkout sale, échec de build, absence de commande de
livraison et orchestration sur faux Docker/dépôts Git jetables). Le test
d'orchestration simule volontairement les appels aux 16 gates et la vérification
des journaux ; **aucune exécution Docker/WSL réelle** de ce nouveau script
n'a encore été observée.

## 24 octobre 2026 — Collecte unittest depuis le contrôleur (recette WSL requise)

- Le mode hôte utilise `arvor_ci_trusted_unittest.py` copié depuis le checkout
  du contrôleur approuvé vers `/trusted` et lancé avec Python `-I`.
  Il découvre les mêmes suites que les anciens lanceurs (Python 3.12/3.14,
  navigateur), redirige les impressions des tests et émet une synthèse JSON
  issue du `unittest.TestResult`. Les tests ignorés restent bloquants.
- Le mode historique garde ses commandes inchangées, mais **ne constitue pas**
  une preuve indépendante puisqu'il donne au candidat accès à `/evidence`.
- La sortie hôte reste bornée par le contrôleur (8 Mio) et l'échec doit bloquer.
  20 tests ciblés de développement (superviseur + collecteur) passent sur
  cette copie rebasée ; cela ne vaut pas la suite Docker/WSL réelle.
- La falsification par un candidat volontairement malveillant dans le même
  interpréteur n'est pas entièrement écartée : revue humaine des tests et
  politique de confiance externe restent nécessaires. Aucune certification de
  provenance, signature, fusion ni livraison PC avant la recette complète.

## 24 octobre 2026 — Contrôle Git `-z` réparé, certification toujours bloquée

- PR #215, commits `8b8f0bc260d517cd9450ad6f739da28584bb5253` et `d6211dbecae694ea16f29da55b9c5beafa3bf670` : le superviseur décode désormais l'octet NUL de `git diff --name-only -z` avec un échappement NUL correct (un seul antislash dans le littéral Python) ; le littéral antérieur avait deux antislashs et rejetait tout diff non vide. Les tests ajoutés couvrent une PR métier multi-fichiers, un diff vide, plusieurs fichiers de contrôle protégés et une sortie tronquée.
- Vérification préalable : compilation AST des deux fichiers et quatre scénarios ciblés dans un harnais Python isolé, réussis. **La suite de tests du dépôt et la recette Docker/WSL au nouveau SHA n'ont pas été exécutées ici** ; elles restent obligatoires.
- Cette PR modifie des scripts de contrôle protégés : elle ne doit pas être acceptée comme son propre candidat CI non fiable. Faire revoir et épingler le contrôleur par une voie de confiance séparée, puis tester une PR métier comme #214.
- Le superviseur impose désormais un plafond de **8 Mio par sortie de gate** ; dépassement, UTF-8 invalide et timeout deviennent KO, sans accumulation illimitée en mémoire hôte. Le groupe de processus est interrompu même si un descendant conserve le pipe. Correctifs `9860178…` / `64de4a6…`, tests `b055a08…` / `28acabaa…`. Les tests système ciblés PASS ne remplacent pas une recette WSL/Docker complète.
- `independent_execution_provenance_verified` reste faux ; aucune signature recevable ni publication d'un statut vert n'est actuellement possible. Les échecs Actions avant runner ne prouvent aucun défaut des tests applicatifs. **Aucune fusion, désactivation d'Actions ou livraison PC.**


## 24 octobre 2026 — Nouveau superviseur Docker avec preuves produites par l'hote (NON ACTIVÉ)

**Motif :** la precedente recette #214 (`a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9`) a reussi les 16 portes, et le controle externe a verifie les SHA256 de 16 logs, mais les logs et le recu provenaient du **conteneur** qui avait acces en ecriture au volume `/evidence`. Cela ne suffit pas a certifier une provenance independante.

**Implementation en cours (PR #215) :**

- `scripts/arvor_ci_host_supervisor.py` fonctionne sur l'hote WSL, hors du clone PR #214. Il exige un `--controller-sha` complet explicite, valide le checkout propre du superviseur et les empreintes des fichiers copies dans `$LAB/trusted`, ainsi que le SHA Git du candidat et l'identifiant immuable de l'image Docker.
- Demarre un conteneur jetable **sans aucun montage /evidence**, sans reseau externe, sans Docker socket, avec workspace et politiques en lecture seule, utilisateur 999 et absence de privileges Linux. **L'hote** inspecte effectivement ces options via `docker inspect`.
- `scripts/arvor_ci_supervised_entrypoint.sh` initialise PostgreSQL 16 jetable et valide les pins directs + extras de la PR contre les paquets installes ; `scripts/arvor_ci_gate.py` est le selecteur de commandes approuvees installe hors du candidat.
- Pour chacune des 16 gates, l'hote effectue son propre `docker exec`, observe le **code de retour du moteur Docker**, capture stdout/stderr, calcule les empreintes SHA256 et sauvegarde les logs/recu uniquement **sur l'hote** en mode 0600.
- Une gate KO conserve une conclusion globale KO. Les compteurs Python/Chromium, l'audit PyPI complet et le JSON ffprobe 75 s restent obligatoires. Les informations d'identite du superviseur, de l'image et de la politique sont consignees dans le recu.
- Le format de recu reste compatible avec `scripts.arvor_ci_evidence_verify` ; **cela n'implique pas** la certification cryptographique de provenance (`independent_execution_provenance_verified` reste faux), la signature, publication GitHub/Slack ou droit de fusion.

**Instructions de test sur WSL** — aucune de ces commandes ne deploie le SaaS Arvor :

```bash
set -eu
export LAB="$HOME/arvor-ci-lab"
export PR_SHA="a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9"
export BASE_SHA="d08fe0afe62f0ea209da239aeade0bd5f042d30d"

cd "${LAB:?LAB non défini}/ci-source"
git status --short
# Si modifications locales, arreter et les preserver avant git switch.
git fetch origin feat/OPS-LOCAL-CI-ATTEST-20261022
git switch --detach SUPERVISOR_SHA_A_EPINGLER

"$LAB/ci-venv/bin/python" -m unittest \
  tests.test_arvor_ci_host_supervisor tests.test_arvor_ci_audit_snapshot \
  tests.test_arvor_ci_trusted_unittest \
  tests.test_arvor_local_ci tests.test_arvor_ci_sandbox \
  tests.test_arvor_ci_evidence_verify -v

install -m 755 scripts/arvor_ci_supervised_entrypoint.sh "$LAB/trusted/"
install -m 644 scripts/arvor_ci_gate.py "$LAB/trusted/"
install -m 644 scripts/arvor_local_ci.py "$LAB/trusted/"
install -m 644 scripts/arvor_ci_trusted_unittest.py "$LAB/trusted/"
install -m 644 scripts/arvor_ci_trusted_gitleaks.toml "$LAB/trusted/"
install -m 644 scripts/arvor_ci_trusted_gitleaksignore "$LAB/trusted/"
mkdir -p "$LAB/host-evidence"
chmod 700 "$LAB/host-evidence"

IMAGE_ID=$(docker image inspect --format '{{.Id}}' arvor-ci:review)
"$LAB/ci-venv/bin/python" -m scripts.arvor_ci_host_supervisor \
  --image-id "$IMAGE_ID" --checkout "$LAB/pr214" \
  --trusted "$LAB/trusted" --evidence "$LAB/host-evidence" \
  --sha "$PR_SHA" --base-sha "$BASE_SHA" --pr 214 \
  --controller-sha "$(git rev-parse HEAD)"
# Après validation du dry-run : meme commande avec --execute.
```

**Exigence avant toute substitution GH :** un run reel de ce mode avec 16/16, verification externe des logs, contre-tests de falsification, signature par une cle hors conteneur avec validation de provenance, identite GH PR SHA/base confirmee, et regle de revue humaine sans contournement. Le statut GitHub "failure" actuel doit rester interprete honnetement. Ne pas activer de publication ni neutraliser les workflows existants tant que ces points ne sont pas effectivement realises.

### Contraintes et risque residuel

Le nouveau mode elimine la capacite directe du conteneur d'editer les preuves **sur l'hote**. Il ne protege pas contre la compromission du demon Docker, de la session utilisateur WSL ou du superviseur lui-meme. Les scripts applicatifs dans la PR peuvent evoluer (les tests doivent toujours etre relus), et le test video 75s reste **synthetique**. La certification independante a distance, les controles GPU/voix/Qwen reels et le deploiement PC restent separes.


---


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
## Recette integrale WSL constatee le 23 octobre 2026

L'utilisateur a communique la sortie du dernier rapport local : **16 portes sur 16 reussies**, code retour 0 sur chaque porte, statut `success`. Identite candidate : PR #214, SHA `24072acbe12d65b3963b7e99d6c48fa6a7afb855`. Le build immuable utilise pendant cette recette est `sha256:ecc09ca2b26f007b940631a8ebcf3fa4b60a757114de2fa6567220637207a5b1`. Les suites Python 3.12 et 3.14 ont chacune execute 390 tests sans erreur ni skip ; Chromium a execute 18 tests. L'audit hors reseau a aussi retourne `No known vulnerabilities found`.

Cette information est une **observation transmise du poste WSL**, pas une execution directement observee par le developpeur de ce script, ni une attestation independante deja signee. Garder les preuves originales et leurs journaux dans le dossier prive ; ne pas modifier `main`, la PR #214 ou le runtime PC.

## Verificateur de coherence externe et limites de confiance

`scripts/arvor_ci_evidence_verify.py` controle en lecture seule :
- correspondance PR / HEAD / base du recu avec le checkout Git et l'ancetre de la base ;
- correspondance SHA256 des **16 journaux** avec les empreintes declarees ;
- coherence des compteurs de regression et du navigateur ;
- preuve JSON synthetique de 75 s, 720x1280, ffprobe et absence de mutation metier ;
- refus des fichiers absents, liens symboliques, fichiers non reguliers ou de taille excessive.

A executer depuis le clone de confiance `ci-source`, **hors du conteneur**. Selectionner l'exact recu issu de la recette reussie ; ici `RECU` est a remplacer :

    RECU="$HOME/arvor-ci-lab/evidence/IDENTIFIANT_DE_LA_RECETTE_SUCCESS.json"
    sudo "$HOME/arvor-ci-lab/ci-venv/bin/python" -m scripts.arvor_ci_evidence_verify \
      --receipt "$RECU" \
      --evidence-dir "$HOME/arvor-ci-lab/evidence" \
      --checkout "$HOME/arvor-ci-lab/pr214" \
      --sha 24072acbe12d65b3963b7e99d6c48fa6a7afb855 \
      --base-sha d08fe0afe62f0ea209da239aeade0bd5f042d30d \
      --pr 214

Le script sort `log-integrity-verified` uniquement quand ces verifications passent. Il affiche explicitement `independent_execution_provenance_verified: false`, `attestation_signed: false` et `merge_or_deploy_authorized: false`.

**Limite de securite fondamentale :** les journaux et le recu ont ete montes en ecriture dans le sandbox sous UID 999 ; un code candidat malveillant pourrait potentiellement manipuler les deux. La coherence de SHA256 et la signature qui suit ne constituent **pas**, a elles seules, une preuve independante de l'execution. Pour un statut externe de confiance, il reste a separer l'ecriture des preuves du code candidat, disposer d'un superviseur hote controle, pinner le code de politique et les empreintes du conteneur, reverifier la tete de PR distante et tester l'anti-rejeu et la publication reelle. Le mode de publication reste desactive.

Le CLI `arvor_ci_attestation sign` exige maintenant `--evidence-dir`, `--checkout`, `--sha`, `--base-sha`, `--pr` pour rendre cette verification **obligatoire avant signature**. Il ne faut toujours pas signer la preuve de succes a des fins de statut externe avant certification de la provenance independante.

Les anciennes sections de ce runbook restent utiles comme historique des incidents, mais leurs mentions d'anciens nombres de tests ou d'un etat Docker non teste sont **perimees** apres la recette du 23 octobre.

## Incident du 24/10/2026 : expiration du cache de vulnerabilites PyPI

**Observation utilisateur (WSL) :** apres restauration de la politique normative AGENTS.md sur la PR #214, nouveau HEAD `a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9`. Les 11 premieres gates reussissent, dont PostgreSQL, les regressions 390/390 sur Python 3.12 et Python 3.14, la syntaxe JS/Python et Chromium. La gate `dependencies` echoue avec `requests.exceptions.ConnectionError: HTTPSConnectionPool(host='pypi.org', port=443)...` lors de l'audit de `annotated-doc==0.0.5`. Un cache HTTP PyPI precharge n'est **pas** une base d'avis hors ligne durable : une entree expiree provoque une tentative de revalidation HTTP, impossible avec `--network=none`.

### Strategie corrigee dans PR #215

- Au **build Docker autorise a acceder a PyPI**, `ci/local/audit_snapshot.py --build` execute `pip-audit --local --strict --format json` pour les environnements **Python 3.12 et 3.14**. Tout code non nul ou paquet non couvert interrompt le build : **aucune exemption de CVE ni de paquet ignore**.
- Le script exige que les paquets et versions audites correspondent a l'inventaire reel de chaque environnement, puis enregistre dans `/opt/arvor/security/` les deux JSON, les hash SHA256, les inventaires et un horodatage UTC.
- Pendant les tests du **candidat sans reseau**, la gate `dependencies` execute `/opt/arvor/py312/bin/python /opt/arvor/security/audit_snapshot.py --verify`. Elle refuse un rapport absent, altere, ne correspondant plus aux paquets installes ou a un environnement Python, presentant une vulnerabilite ou un skip, ainsi qu'un snapshot age de plus de **24 heures**. Elle **ne contacte pas PyPI** et ne depend pas du cache HTTP.
- Les rapports sont inclus **dans l'image Docker immuable**, qui doit etre identifiee par son SHA256. Le code candidat et ses donnees ne doivent pas y avoir acces en ecriture. Les exigences directes de `requirements.txt` candidat sont toujours revalidees sur les deux interpreteurs par le point d'entree.
- **Limite importante :** ce mecanisme prouve la conformite a l'etat connu de PyPI **au moment du build**, pas l'absence eternelle de vulnerabilite. Toute image de plus de 24 heures est refusee et doit etre reconstruite avec reseau de confiance. Les vulnerabilites du systeme Debian/Chromium requierent par ailleurs des controles distincts.
- Tests negatifs ajoutes dans `tests/test_arvor_ci_audit_snapshot.py` : expiration, horloge future, empreinte alteree, CVE introduite, dependance ignoree, inventaire modifie, environnement manquant et echec de l'auditeur pendant le build.

### Revalidation WSL requise apres le correctif

Dans `~/arvor-ci-lab/ci-source` actualise au SHA courant de PR #215, reconstruire l'image **obligatoirement** puis recuperer son nouvel identifiant :

    docker build --progress=plain -f ci/local/Dockerfile -t arvor-ci:review .
    IMAGE_ID=$(docker image inspect --format '{{.Id}}' arvor-ci:review)

Verifier sans reseau, en lecture seule et UID 999 :

    docker run --rm --network=none --read-only --cap-drop=ALL \
      --security-opt=no-new-privileges --user=999:999 \
      "$IMAGE_ID" /opt/arvor/py312/bin/python \
      /opt/arvor/security/audit_snapshot.py --verify

Executer ensuite les tests unitaires :

    "$HOME/arvor-ci-lab/ci-venv/bin/python" -m unittest \
      tests.test_arvor_ci_audit_snapshot tests.test_arvor_local_ci \
      tests.test_arvor_ci_sandbox tests.test_arvor_ci_evidence_verify -v

Recopier `scripts/arvor_local_ci.py` et `scripts/arvor_ci_entrypoint.sh` actualises dans `$LAB/trusted/`, et relancer les 16 portes au SHA de PR #214 `a4f885ead324fbf7aa7fc61be3f37cddc0bfd6e9`. **Ne pas annoncer la recette reussie avant le rapport des 16 portes et son controle externe.**

Les GitHub Actions restent bloquées par une restriction de facturation/quota et doivent etre revalidees selon la politique en vigueur. Cette correction n'autorise ni une fusion forcee, ni l'activation de MEP PC, ni un statut GitHub atteste sans superviseur independant.

## Durcissement securite du snapshot PyPI — revue du 24 octobre 2026

Une revue externe a identifie trois risques supplementaires de l'ancienne proposition :

1. `docker build` peut reprendre une couche en cache sans interroger PyPI. Le Dockerfile exige maintenant `SECURITY_AUDIT_REFRESH` : cette valeur unique invalide uniquement l'etape finale d'audit.
2. Le rapport doit porter sur **l'ensemble des distributions effectivement installees** dans les deux environnements Python, pas uniquement sur `requirements.txt`. Le manifeste embarque contient le nom/version de chaque distribution, l'empreinte SHA256 canonique de son inventaire, la version exacte `pip-audit==2.10.1`, le service `pypi`, l'horodatage et les empreintes des deux rapports JSON. Le controle hors reseau relit chaque distribution installee.
3. La date du build ne doit pas travestir la fraicheur du cache HTTP. Le build emploie un **cache PyPI temporaire neuf** pour chaque nouvelle analyse, puis detruit le cache : les 24 h commencent seulement apres deux audits reussis. Aucun `--ignore-vuln`, `--skip-editable` ni exemption implicite n'est autorise.

### Etats de diagnostic

Le code principal du controle reste 0 uniquement si toutes les preuves sont `OK`. Toute autre classification bloque la recette : `VULNERABLE` (vulnerabilite declaree), `PREUVE_PERIMEE` (>24 h ou horloge incoherente), `PREUVE_NON_CORRESPONDANTE` (inventaire/empreinte/version d'auditeur/information incomplete), `ERREUR_INFRA` (PyPI, entree-sortie ou outil indisponible). Avant les portes de la CI, la verification des dependances directes du candidat signale `RECONSTRUCTION_IMAGE_REQUISE` pour une version ou une dependance extra absente : ce n'est **pas** une CVE. Les categories ne transforment jamais un echec de commande en succes.

### Commande du prochain build WSL

Depuis le checkout d'une revision revue et epinglee de PR #215 :

    docker build --progress=plain \
      --build-arg SECURITY_AUDIT_REFRESH="$(date -u +%Y%m%dT%H%M%SZ)" \
      -f ci/local/Dockerfile -t arvor-ci:review .

    IMAGE_ID=$(docker image inspect --format '{{.Id}}' arvor-ci:review)
    docker run --rm --network=none --read-only --cap-drop=ALL \
      --security-opt=no-new-privileges --user 999:999 \
      "$IMAGE_ID" /opt/arvor/py312/bin/python \
      /opt/arvor/security/audit_snapshot.py --verify

    "$HOME/arvor-ci-lab/ci-venv/bin/python" -m unittest \
      tests.test_arvor_ci_audit_snapshot tests.test_arvor_local_ci \
      tests.test_arvor_ci_sandbox tests.test_arvor_ci_evidence_verify -v

Actualiser les deux fichiers de `$LAB/trusted` avant relance de la PR #214. Toujours donner **l'ID immuable** de l'image, pas son tag, au lanceur. Aucune validation de code ou image n'est revendiquee avant execution sur le PC WSL.

### Gestion de la duree de validite

**Duree maximale : 24 h.** Pour eviter qu'une recette soit interrompue par une image expiree, prevoir une reconstruction quotidienne **hors du conteneur de code candidat**, sur un hote de confiance avec acces reseau sortant a PyPI. La reconstruction doit executer le build ci-dessus avec nouveau jeton `SECURITY_AUDIT_REFRESH`, puis le test `--verify` hors reseau. Stocker/consigner l'ID d'image et le moment de construction. Un echec de mise a jour laisse la derniere image en place mais **n'autorise pas** la recette si elle est expiree. Aucune tache planifiee PC n'est activee depuis cette PR ; elle sera a mettre en place explicitement dans l'exploitation WSL selon sa disponibilite.

Le fichier GitHub `.github/workflows/security-deps.yml` est conserve et reste un controle en ligne **complementaire**, avec son calendrier hebdomadaire, quand la facturation GitHub permettra de lancer les runners ; son statut KO n'est ni masque ni remplace par un faux PASS local. Aucune fusion forcee n'est autorisee.

### Evolutions de dependances / exceptions

Pour une PR qui modifie `requirements.txt`, reconstruire une image **candidate jetable avant merge** a partir de cette PR revue, verifier la liste installee et son audit en ligne au build, puis relancer l'execution isolee. Ne pas valider une dependance uniquement parce qu'une image courante existe. Ce flux evite le cercle vicieux « il faut merger pour reconstruire l'image ».

Les exceptions `--ignore-vuln` ne sont **pas disponibles** dans l'implementation courante : toute vulnerabilite identifiee bloque le build. Si un jour des exemptions sont autorisees, elles devront etre approuvees separément, liees a une justification, une echeance, un paquet+version+identifiant CVE et bloquees automatiquement apres la date d'expiration.

Risques residuels : une CVE publiee **apres** le dernier build peut rester invisible jusqu'a la prochaine reconstruction ; l'audit PyPI des dependances Python n'equivaut pas a un scan de l'OS, des conteneurs ou du navigateur. Le service de supervision/attestation independant n'est toujours pas livre. Aucune action ne modifie la configuration du PC de production ni les donnees metier.

## 25 octobre 2026 — Provenance hôte vérifiée, en attente de recette finale #215

Le vérificateur n'accorde plus la provenance à partir des champs booléens du
reçu. `arvor_ci_host_supervisor.py` écrit un journal hôte séparé `RUN_ID.host.json`
(mode 0600, dossier 0700) qui n'est pas monté dans le conteneur. Il contient
l'inspection Docker capturée par l'hôte, l'ID du conteneur, les codes retour des
commandes `docker exec`, l'empreinte de sortie de chaque gate, ainsi que les
empreintes des fichiers de politique. Le reçu pointe vers le hash du journal.

`arvor_ci_trust.py` calcule l'identité de politique depuis la liste versionnée
de fichiers actifs, `AGENTS.md`, le runbook, le manifeste de tests et tous les
workflows GitHub. La vérification exige les arguments de confiance explicites
(controller clean/pinné hors checkout candidat, bundle de politique, ID image
sha256 attendu, SHA de politique). Elle vérifie aussi que le journal, le reçu
et les logs sont des fichiers privés détenus par l'hôte; le Docker inspect
réel satisfait l'isolation; chaque gate correspond à la commande approuvée et
à son code de retour observé; tous les hashes, compteurs et timestamps passent.
La valeur de provenance de sortie est calculée après ces contrôles. Une valeur
booléenne présente dans un reçu est ignorée.

Le signataire reprend exactement l'objet et les octets vérifiés, signe le reçu
et le résumé de provenance ensemble par Ed25519, puis le publisher exige ces
champs dans une enveloppe vérifiable. La clé privée doit être un fichier 0600,
propriétaire courant, hors dépôt, checkout candidat, bundle et preuves. Aucun
secret n'est transmis au conteneur. La revue d'une modification des contrôles
reste obligatoire : le superviseur échoue avec
`CONTROL_PLANE_REVIEW_REQUIRED` dès qu'un candidat touche `scripts/arvor_ci_*`,
`ci/local/`, `.github/workflows/`, `AGENTS.md` ou le runbook de migration.
Ne pas désactiver ni contourner ce refus.

### Refaire la recette WSL après le SHA final du contrôleur

Utiliser un clone autonome et propre pour le contrôleur final ainsi qu'un clone
propre de la tête actuelle de #214. Le SHA du contrôleur doit avoir reçu une
revue séparée. Vérifier d'abord que le poste WSL dispose de Docker ; ne jamais
lancer ces commandes contre les volumes Arvor de production. La qualification
crée ses propres bases PostgreSQL dans le conteneur et deux dossiers uniques.

```bash
export LAB="$HOME/arvor-ci-lab"
export CONTROLLER_SHA="SHA_COMPLET_REVU_DE_215"
export PR214_SHA="SHA_COMPLET_ACTUEL_DE_214"
export BASE_SHA="SHA_COMPLET_MAIN"
cd "$LAB/ci-source"
test "$(git rev-parse HEAD)" = "$CONTROLLER_SHA"
test -z "$(git status --porcelain)"
bash scripts/qualify_arvor_ci_wsl.sh "$CONTROLLER_SHA" "$PR214_SHA" "$BASE_SHA"
```

La sortie imprime les chemins neufs `Politique de confiance` et `Preuves
privées`, l'ID image et le `run_id`. Le script ne signe et ne publie rien.
Après avoir contrôlé que le reçu correspond à cet unique `run_id`, réutiliser
l'ID image imprimé et calculer le pin depuis le même checkout :

```bash
export RECEIPT="CHEMIN_PRIVE/RUN_ID.json"
export HOST_OBSERVATION="CHEMIN_PRIVE/RUN_ID.host.json"
export EVIDENCE_DIR="CHEMIN_PRIVE"
export TRUSTED_POLICY="CHEMIN_IMPRIME_DE_LA_POLITIQUE"
export IMAGE_ID="sha256:ID_IMAGE_IMPRIME"
export POLICY_SHA256=$("$LAB/ci-venv/bin/python" -c 'from scripts.arvor_ci_trust import policy_digest; import sys; print(policy_digest(sys.argv[1]))' "$LAB/ci-source")
"$LAB/ci-venv/bin/python" -m scripts.arvor_ci_evidence_verify \
  --receipt "$RECEIPT" --host-observation "$HOST_OBSERVATION" \
  --evidence-dir "$EVIDENCE_DIR" --checkout "$LAB/pr214" \
  --trusted-controller "$LAB/ci-source" --trusted-policy "$TRUSTED_POLICY" \
  --controller-sha "$CONTROLLER_SHA" --image-id "$IMAGE_ID" \
  --policy-sha256 "$POLICY_SHA256" --sha "$PR214_SHA" \
  --base-sha "$BASE_SHA" --pr 214
```

Signer seulement depuis `$LAB/ci-source`, jamais depuis le dépôt candidat. Le
fichier clé reste dans un emplacement distinct, extérieur au dépôt et au
conteneur. L'output signé et les logs sont privés. Le signer exige tous les
pins ci-dessus et l'objet exact retourné par le vérificateur; il ne relit pas
le reçu après validation.

La publication est une étape distincte et elle exige une signature vérifiable,
une preuve récente, la tête distante exacte et une identité de contrôleur,
politique et image conforme. Pour éviter une seconde commit-status après une
réponse GitHub perdue, le publisher réconcilie l'URL unique de run dans
l'historique avant tout POST, puis relit la PR immédiatement avant écriture.
Pour Slack, un échec laisse un marqueur `pending`; aucune relance automatique
n'a lieu. N'utiliser `--confirm-slack-not-delivered` qu'après vérification
indépendante de l'absence du message. L'environnement
`ARVOR_LOCAL_CI_FULL_PARITY_APPROVED` reste une barrière opérationnelle
supplémentaire et ne vaut jamais preuve de provenance.

**État à la date de cette note : code et tests unitaires en cours de revue dans
#215 ; aucune nouvelle recette Docker/WSL, aucune signature, aucun statut
GitHub et aucune notification Slack n'ont encore validé son SHA final.** La
recette WSL précédente liée à #214 avec contrôleur `7c73cd…` et reçu
`41048767-…` est historique : elle ne prouve pas ce code modifié ni une nouvelle
exécution exacte-SHA. Le contrôle `CONTROL_PLANE_REVIEW_REQUIRED`, une revue
séparée, les checks requis et le statut GitHub effectif restent des conditions
avant toute fusion. L'absence d'accès aux règles de protection du dépôt privé
ne prouve pas qu'aucun contrôle n'est requis.
