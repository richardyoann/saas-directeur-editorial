# Administration : échec partiel de source — 7 novembre 2026

Correctif limité du point 3 de la revue #239, base cea01ecc12b1022287a75c4de84f0fab04395673. Le chargement n'est considéré disponible que lorsque conception, commits et CI ont répondu. Une panne de commits ou CI ne doit pas être présentée comme une source opérationnelle vide. Par prudence, une panne partielle rend ce panneau indisponible et efface les données chargées ; aucun détail d'exception fournisseur n'est affiché pour ces rejets. La catégorie non configurée reste réservée au 503 du point d'entrée conception.

Validation ciblée : trois scénarios Node exécutant la vraie fonction loadAdmin, API simulée (source valide vide, panne commits, panne CI). Échec reproduit avant correction, puis 3/3 réussis ; syntaxe JS vérifiée. Commande : node tests/js/admin_source.test.cjs. Aucun service privé ni donnée métier utilisé. Ce contrôle ne remplace pas Chromium, la régression complète, l'isolation tenant et la revue au SHA final, qui restent à qualifier.

Installation/déploiement : aucun script, secret, schéma ou prérequis modifié. Fichier statique livré selon la procédure existante seulement après validation humaine du SHA complet. Retour arrière par revert sans mutation de données. Correctif indépendant de la pagination #240 ; pas de fusion ni MEP annoncée.
