# Journal : préserver les traces disponibles en panne partielle — 9 novembre 2026

## Périmètre

Correctif du comportement de `loadJournal()` dans le lot 4. Si l'historique des traitements ou celui des décisions échoue, le journal conserve les lignes de la source qui a répondu et affiche un avertissement explicite, sans détail d'exception fournisseur. Si les deux sources échouent, le journal reste indisponible et affiche les deux catégories fixes d'erreur.

Aucun endpoint, contrat API, schéma, secret ou configuration n'est modifié. Aucun résultat éditorial n'est accepté automatiquement : les décisions affichées restent les traces humaines enregistrées.

## Preuve ciblée

Le test `tests/js/journal_partial_trace.test.cjs` exécute les fonctions de production `loadJournal()`, `journalVisible()` et `renderJournal()` dans une VM Node avec API simulée. Il couvre succès complet, panne history avec décisions conservées, panne reviews avec traitements conservés, et panne des deux sources. Test rouge constaté à l'ancien code (`arvor_next.js` blob `2a116afeee97ed0dcfa37dd3bdcd7a069295c398`), puis 4/4 scénarios réussis et `node --check` sur les fonctions actuelles extraites du blob `ad04c835a5f601be71097144606850b40b33a1f2`. Le runner complet doit être exécuté depuis un checkout au SHA final ; cette preuve ciblée ne remplace pas Chromium, la régression complète ni les tests PostgreSQL/isolation.

## Installation, déploiement et retour arrière

Aucun changement de procédure d'installation ou de déploiement : fichier frontend statique uniquement. Aucune MEP, fusion ou migration n'est réalisée. Retour arrière par revert du changement frontend et du test/document associé ; aucune donnée n'est modifiée.
