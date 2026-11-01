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
