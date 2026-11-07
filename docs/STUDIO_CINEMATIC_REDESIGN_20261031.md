# STUDIO — Refonte UX/UI cinématographique — Lot 1 (31 octobre–1 novembre 2026)

**Statut :** implémenté sur branche dédiée — **Lot 1 validé sur contrôle diff** (non fusionné).
**Branche :** `refactor/studio-cinematic-20261031`
**SHA de base :** `24e49d3bd4ee846c51822ba0cc0e3c48bdf542fc` (`origin/main`)

## Objet du lot

Conformément à l'ordre de mission « Arvor Studio cinématographique » (cadrage 2026-11-01),
le Lot 1 porte la **première brique livrable** de la refonte : le design system cinématographique,
le shell de navigation et le tableau de bord (écran n°1).

## Périmètre livré

- Design system centralisé (`apps/web/arvor_next.css`) : tokens de palette mission
  (`--bg #0B1115`, `--panel #121B20`, `--panel-2 #18242A`, `--line #29373C`, `--text #ECF0EC`,
  `--muted #91A19F`, `--gold #D2B175`, `--teal #6AC4B5`, `--red #EB917C`), typographies
  éditoriale/sans/mono locales (aucune police externe), espacements, radii, ombres.
- Shell : sidebar groupée (espace de création / travaux & mémoire), topbar, contenu, mobile drawer,
  états réduits (`prefers-reduced-motion`).
- Tableau de bord (`overview`) : métriques réelles issues de `/studio/api/runs`, actions humaines
  prioritaires, activité récente, état dérivé du pipeline.
- Vues nouvelles raccourcies : Conception (sélection d’histoire → atelier), Production (contexte média
  réel par histoire), avec états vides explicites.
- Navigation : six destinations déclarées (`overview`, `stories`, `conception`, `production`, `journal`,
  `admin`) branchées sur les endpoints réels existants.

## Non-périmètre (Lots suivants)

- Lots 2 à 5 : bibliothèque complète, atelier scénario/scènes/personnages, production image/voix/vidéo,
  journal et administration approfondis, qualification finale.
- Aucun endpoint API backend n’a été modifié : les écrans nouveaux consomment les contrats existants.

## Tests

- `tests/test_studio_cinematic_redesign.py` : contrats design tokens, navigation shell, implémentation
  dashboard/vues, typographies, responsive.
- Suites existantes touchées : `tests.test_studio`, `tests.test_arvor_reference` — **OK (20 tests)**.
- Contrôle CI local prévu : `scripts/arvor_local_ci.py` (syntaxe JS via `node --check`,
  régressions Python 3.12/3.14, PostgreSQL jetable, sécurité, navigateur).

## Limites

- Les métriques dashboard sont agrégées sur les histoires chargées (limite pagination 50) — non exhaustif.
- Le pipeline est dérivé des états réels des runs, sans fabrication d’état.
- Aucun rendu navigateur réel n’a été exécuté dans ce lot ; recette PC distincte.

## Lots 2–3 — mises à jour de documentation (01 novembre 2026)

### Lot 3 — vue Production — corrections de contrôle (2026-11-01)

- **Export vidéo (LOT3-01)** : le bouton « Exporter le MP4 1080 × 1920 » est désormais rattaché à
  `exportVideo()`, qui réutilise la route privée de téléchargement média
  (`GET /studio/api/runs/{run_id}/media/{media_id}/content`), vérifie l’approbation, le statut
  vidéo `ready`, l’identifiant média et l’appartenance au `run_id` sélectionné, puis déclenche le
  téléchargement via blob. Le toast de succès n’est émis qu’après une réponse `ok`. Le scénario JSON
  reste exporté via `exportStory()` (rattachement distinct).
- **État de navigation (LOT3-02)** : changement d’histoire (`navigate`) réinitialise `prodData`,
  `mediaData` et `historyData`.
- **États d’erreur (LOT3-03)** : `prodError` alimente un état « Lecture de la production impossible »
  distinct du chargement inactif ; rechargement automatique après échec via la navigation.
- **Contrôle qualité (LOT3-04)** : la qualité distingue désormais présence des médias,
  validation technique (scénario approuvé, 75 s, scènes et images complètes, voix `ready`) et
  validation artistique humaine (`approved`). Une liste d’images manquantes vide n’est acceptée que
  si la liste des scènes est réellement renseignée.
- **Fidélité visuelle (LOT3-05)** : recette de comparaison avec la maquette cinématographique
  (lecteur vertical 9:16, scènes, timeline, inspection, voix, sous-titres, qualité, décisions) —
  éléments encore absents documentés lors de la qualification finale.

## Lot 4 — Journal et administration (02 novembre 2026)

**Branche :** `refactor/studio-cinematic-lot4-journal-admin-20261031`
**SHA de base :** `3c6f61a8864062a88c074d42f680972c480358fd` (Lot 3 corrigé, PR #234)

### Fonctionnalités implémentées

- Journal (`journal`) : consommation des traces réelles
  (`GET /studio/api/runs/{id}/history`, `GET /studio/api/runs/{id}/reviews?limit=50`) pour l’histoire
  sélectionnée. Les lignes sont construites depuis les snapshots d’étapes IA et les décisions humaines
  réelles (action, revision, statut, provenance, agent) — plus aucune fabrication à partir des seules
  dates de création.
- Filtres (Tout / Décisions humaines / Traitements IA), recherche plein texte, pagination réelle
  (15 traces par page), état de chargement, état vide (histoire non sélectionnée) et état erreur.
- Administration (`admin`) : états source distincts (opérationnel / indisponible / non configuré) via
  `adminError` ; le suivi GitHub est en lecture seule ; les conclusions CI sont affichées telles quelles
  (aucun `skipped` transformé en succès).

### Fichiers modifiés

- `apps/web/arvor_next.js`, `tests/test_studio_cinematic_redesign.py`, `browser_checks/test_studio_browser.py`,
  `docs/STUDIO_CINEMATIC_REDESIGN_20261031.md`.

### API utilisées/modifiées

- Seules des routes GET existantes du Studio sont consommées : aucun endpoint backend modifié.

### Tests exécutés

- `tests/test_studio_cinematic_redesign.py` — **OK (23 tests)** (dont 6 tests de non-régression ajoutés en finalisation Lot 5).
- Suites touchées : `tests.test_studio`, `tests.test_arvor_reference`, `tests.test_studio_conception`,
  `tests.test_qa_lot1` — **OK**.

### Contrôles sécurité

- Aucune mutation métier, aucun endpoint backend modifié, aucune donnée fictive injectée.

## Lot 5 — Qualification finale (02 novembre 2026)

**Branche :** `refactor/studio-cinematic-lot4-journal-admin-20261031` (au 2026-11-02, lot 4 terminé)
**SHA de base :** `b886e98260d6874b89efdd241ab421320ff306b4`
**SHA final du lot :** `8aeb5baf40f7a36952e722f76d72f11f63fdce21` (dernier commit de finalisation Lot 5 : reset prodError navigation, statut decision humaine)

### Régression

- `scripts/run_regression.py` sur l’état final des PR empilées (Lot 4) : **611 tests, 0 échec, 0 erreur**, 58 sauts.
- Sauts (58) : uniquement les suites « dedicated PostgreSQL test target not configured » / « PostgreSQL
  required » — environnement local sans base jetable ; non liés aux changements UI/tests/docs.
- Plancher CI local : `MIN_REGRESSION_TESTS = 390` — dépassé (611).

### Qualification finale executee via le mecanisme officiel (Lot 5 finalisation)

- `bash scripts/qualify_arvor_ci_wsl.sh 079317cd912168ec58ce4df377c49441cfc40186 239 8aeb5baf40f7a36952e722f76d72f11f63fdce21 3c6f61a8864062a88c074d42f680972c480358fd`
  → exit **0**, `ARVOR_CI_LOCAL_GATES_AND_LOG_INTEGRITY_PASS`.
- 16/16 portes hote OK : db_prepare_312, regression_312, sql_benchmark_312, db_prepare_314,
  regression_314, sql_benchmark_314, syntax_js, syntax_js_reference, syntax_js_next, syntax_py,
  browser, dependencies, secrets, supply_chain, risk_review, video_75.
- Receipt : `/home/yoann_admin/arvor-ci-lab/evidence-qualification.DlkivIbI/0539b2d5-7f6e-43a4-956c-6922818226e9.json`
  → status `success`, `verified_logs: 16`, `independent_execution_provenance_verified: true`,
  `attestation_signed: false`, `merge_or_deploy_authorized: false`.
- Preuve d’integrite des logs/recus verifiee (`arvor_ci_evidence_verify`); signature et publication
  distinctes; merge/deploiement NON.

### Corrections de finalisation Lot 5 (Étape 1, commit `Lot 5 — corrections revue`)

- Navigation journal : contexte d’histoire conservé (`navigate(b.dataset.route,state.storyId)`).
- Décision humaine : contrat réel des reviews (`action`, `actionLabel`, `status`, `version`,
  `provenance`, `agent`, `human`).
- Traces plein/partiel : gestion des échecs historiques (`failures` → `journalError`).
- Validation artistique séparée de l’approbation scénario (`pending_human` / `not_started`).
- Disponibilité sources partielles : `source_truncated` / `sourcePartial`.
- Syntaxe JS : deux erreurs de syntaxe réelles corrigées lors de la finalisation (ternaire de rendu
  vidéo `<video` en position d’expression non collé aux template literals ; interpolation du bloc
  sources dans le rendu admin).

### Contrôles restants de qualification (à exécuter / attester)

- `node --check apps/web/arvor_next.js` : **non exécutable dans cet environnement** (Node présent
  uniquement sous forme de `node.exe` Windows via `/mnt/c/Program Files/nodejs`, non exécutable sous
  WSL Linux sans Wine) ; contrôle CI prévu (`syntax_js_next`). Vérifications locales équivalentes
  effectuées : compilation QuickJS OK + parse tree-sitter sans `ERROR`/`MISSING` sur le SHA final.
- Parcours Chromium complets : **non exécutable localement** (Playwright/Chromium absents) ; nouveaux
  parcours ajoutés (`test_next_studio_journal_and_admin_states`) ; contrôle CI prévu (`browser`).
- Résolutions 1920×1080, 1366×768, 768×1024, 390×844, 360×800 : **à capturer** (aucune capture disponible
  à ce stade).
- Sécurité : diff final frontend/tests/docs uniquement — aucune route backend, aucune authentification
  nouvelle, aucun secret ajouté.

### Écarts à la maquette

- Captures et comparaison visuelle : **en attente** (voir ci-dessus).

## Lots suivants

- Lot 5 : qualification finale (régression, CI locale 16 contrôles, navigateur, résolutions,
  sécurité, documentation, revue finale).

## Lot 5 bis — correctifs UX issus de la revue indépendante (6 novembre 2026)

**État :** correctifs frontend préparés sur `fix/studio-lot5-ux-20261105`. La recette
Chromium et la qualification visuelle restent bloquées par l'environnement WSL décrit
ci-dessous ; ce lot n'est pas qualifié GO.

### Corrections

- La navigation devient un tiroir compact à 930 px et moins, au lieu d'une barre verticale
  pleine largeur sur tablette. Le contrôle de menu expose son état, conserve la route et
  l'histoire sélectionnée, rend les liens inactifs au clavier quand le tiroir est fermé et
  rend le focus au contrôle de menu à la fermeture.
- Le bandeau mobile permet le retour à la ligne et réduit ses colonnes ; les grilles passent
  à une colonne à 690 px. La page ne masque pas ses débordements en créant un défilement
  horizontal global.
- Les onglets d'administration indiquent le défilement sur petit écran, gardent leur
  barre de défilement visible et supportent les flèches gauche/droite ainsi que Home/End.
  Les états GitHub `operational`, `unavailable` et `not_configured` restent issus de l'API.
- Le journal sépare type, action, acteur, version, statut, provenance et résultat dans des
  champs nommés ; les dates absentes ou invalides apparaissent comme « Date inconnue ».
  Il continue de lire uniquement les endpoints d'historique et de décisions réels.
- La Production ne montre qu'une action MP4, inactive tant que l'approbation, le statut prêt,
  l'identifiant média et l'appartenance exacte au run sélectionné ne sont pas confirmés.
  La réponse de téléchargement doit aussi avoir le type MIME `video/mp4`. Le JSON storyboard
  reste un export distinct. Aucun contrat serveur ou contrôle d'accès n'a été retiré.

### Vérifications et limites

- `node --check apps/web/arvor_next.js` : réussi avec Node 26.13.0.
- `python -m unittest tests.test_studio_cinematic_redesign tests.test_studio tests.test_studio_conception tests.test_arvor_reference -v` : 39 tests réussis.
- `python -m unittest discover -s browser_checks -p test_studio_browser.py -v` : 23 tests réussis,
  sans skip, dans le conteneur isolé local d'ID `sha256:67d3e41d12b1064ca484db7b32116e4c8807dd00d8898bc5e4b95de2f4e4c83b`.
  Ce conteneur a utilisé Chromium Playwright, réseau désactivé et le checkout monté en lecture seule.
- Les nouveaux parcours contrôlent les six routes aux cinq résolutions, le tiroir clavier/tactile,
  le contexte d'histoire, les onglets d'administration, les métadonnées de journal et les états
  MP4 absent/interdit/prêt. Ces parcours utilisent la fixture navigateur jetable décrite dans
  `tests/studio_browser_fixture.py` ; ce n'est pas une recette sur PostgreSQL/LLM du PC.
- En conséquence, aucune nouvelle capture des 30 vues ni comparaison de parité n'est
  attestée par ce travail. Les états Histoires bibliothèque/détail et Conception
  sélectionné/vide demandent une recette dédiée sur état métier comparable ; le présent
  patch ne fabrique aucune donnée pour les faire correspondre.
- Le tableau de bord conserve ses agrégats et activités réellement renvoyés par l'API.
  Sa composition diffère encore de la référence ; cet écart produit doit être arbitré
  séparément. Les polices sont des fontes système et les images sont locales, sans appel
  Google Fonts ou Unsplash dans le Studio.
- **Verdict Lot 5 bis : NO GO pour fusion** tant que les captures aux cinq résolutions,
  les 30 comparaisons d'états équivalents et les 16 portes officielles de CI sur le SHA
  final n'ont pas été obtenues. La réussite des 23 parcours de développement ne vaut pas
  qualification 16/16. Aucune fusion ni livraison PC n'a été exécutée.


## Qualification Lot 5 — passe de contrôle locale (7 novembre 2026, session agent)

**Contexte :** reprise de la mission « correction, mise en conformité et préparation MEP du lot 5 » sur PR #241 (`fix/studio-lot5-ux-20261105`, HEAD `da0aeca61d7df2befbdcbfd951941c6ab50b5af0`, DRAFT). Dossier détaillé : `docs/LOT5_MEP_DOSSIER_20261107.md`.

### Contrôles exécutés (preuves locales, SHA `da0aeca`)
- `node --check apps/web/arvor_next.js` : **OK** (Node 24, runner externals `/home/yoann_admin/.local/share/editorial-actions-runner/externals.2.338.2/node24/bin/node`).
- `python -m unittest tests.test_studio_cinematic_redesign -v` : **25/25 OK** (venv `/home/yoann_admin/editorial-runtime/current/.venv`).
- `python -m unittest tests.test_studio tests.test_arvor_reference -v` : **12/12 OK**.
- `python -m unittest discover -s tests -p 'test_studio*.py' -v` : **37/37 OK**.
- Inventaire recette visuelle `/tmp/arvor_visual_review_lot5` : 30 maquettes + 30 captures app + 12 comparaisons initiales ; **18 comparaisons composites ajoutées le 2026-11-07** (1366×768, 768×1024, 360×800 × 6 écrans) depuis originaux existants, `MANIFESTE.json` mis à jour avec `generated_from_existing_captures:true`. **Ce ne sont pas des recaptures applicatives du HEAD.**

### Contrôles non exécutés / bloquants restants
- Recapture application 30 vues × 5 résolutions sur le SHA final, états métier équivalents (sans fabrication), comparaison/inspection visuelle humaine.
- 16 portes officielles CI locale sur clone autonome propre du SHA final (mécanisme `arvor_local_ci` / qualification officielle) — historique 16/16 sur `8aeb5ba` ne couvre pas `da0aeca`.
- Parcours navigateur/Chromium complets en environnement qualifié (conteneur Playwright documenté absent localement).
- Régression complète + PostgreSQL jetable + audits dépendances/supply chain/gitleaks via mécanisme officiel.
- Revue indépendante formelle.
- Arbitrage produit : composition tableau de bord vs maquette.

### Verdict
**NO-GO fusion / NO-GO validation MEP.** Aucune fusion ni déploiement PC effectué.
