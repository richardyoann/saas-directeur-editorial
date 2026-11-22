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

### Lots suivants

- Lot 4 : journal et administration (traces réelles, contrats d’historique/décisions/production).
- Lot 5 : qualification finale (régression, CI locale 16 contrôles, navigateur, résolutions,
  sécurité, documentation, revue finale).
