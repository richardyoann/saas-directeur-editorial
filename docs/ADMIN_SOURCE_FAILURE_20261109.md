# Administration : échec partiel d'une source — 9 novembre 2026

Le panneau d'administration n'est considéré opérationnel que si les trois sources (conception, commits, CI) répondent. Une panne de commits ou de CI ne doit pas être affichée comme une source opérationnelle vide. En cas d'échec, le panneau devient indisponible et les données précédemment chargées sont effacées. Les détails d'exception fournisseur ne sont pas exposés. La catégorie « non configurée » reste réservée au 503 du point d'entrée conception.

## Validation ciblée

Depuis la racine du dépôt :

```sh
node tests/js/admin_source.test.cjs
```

Cinq scénarios Node exécutent la fonction `loadAdmin` avec une API simulée : réponse vide valide, échec commits, échec CI, erreur générique conception et conception 503. Les scénarios d'échec démarrent avec des données antérieures préchargées et vérifient leur effacement, le message sûr et un unique rendu. Le test a échoué avant le correctif car une panne partielle ne renseignait pas `adminError`, puis les cinq scénarios ont réussi sur l'extrait de la fonction récupéré à la tête de cette branche ; `node --check` sur cet extrait passe aussi. Aucun service privé ni donnée métier n'est utilisé. Ceci ne remplace pas Chromium, la régression complète, les contrats API/PostgreSQL, l'isolation tenant ou une revue au SHA final.

Aucun changement d'installation, de configuration, de schéma ou de déploiement. Après validation des contrôles, le fichier statique suit la procédure de livraison existante. Retour arrière : revert du correctif et de son test/document, sans modification de données.
