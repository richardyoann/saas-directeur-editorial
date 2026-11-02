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
**SHA final du lot :** `cd79a8b2e0ce31a430757996dcc7436c07e13b4d` (dernier commit de finalisation Lot 5)

### Régression

- `scripts/run_regression.py` sur l’état final des PR empilées (Lot 4) : **611 tests, 0 échec, 0 erreur**, 58 sauts.
- Sauts (58) : uniquement les suites « dedicated PostgreSQL test target not configured » / « PostgreSQL
  required » — environnement local sans base jetable ; non liés aux changements UI/tests/docs.
- Plancher CI local : `MIN_REGRESSION_TESTS = 390` — dépassé (611).

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