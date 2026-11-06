# Réinitialisation de la pagination du journal — 6 novembre 2026

Correctif limité du point 2 de la revue #239, base cea01ecc12b1022287a75c4de84f0fab04395673. Le rendu lisait state.journalPage, tandis que chargement, navigation et déconnexion remettaient à zéro une variable distincte. Tous utilisent désormais state.journalPage, initialisé à 1.

Validation : test Node isolé du vrai chargeur JavaScript, deux scénarios (sans histoire et chargement de B depuis la page 3). Échec reproduit avant correction (3 au lieu de 1), puis deux scénarios réussis et syntaxe JS vérifiée. Commande depuis la racine : node tests/js/journal_page.test.cjs. Tests réseau simulés, aucun accès API/DB/Qwen ou contenu privé. Le test ne remplace pas le parcours Chromium A page 3 → B page 1 ni la CI complète au SHA final, encore à qualifier.

Installation/déploiement : aucun prérequis, script, configuration ni migration modifié ; fichier statique livré selon la procédure existante seulement après validation humaine du SHA exact. Retour arrière : revert de ce correctif sans mutation de données. Les défauts de pagination serveur et d'état admin partiel restent ouverts. Aucun merge, déploiement ni acceptation métier annoncé.
