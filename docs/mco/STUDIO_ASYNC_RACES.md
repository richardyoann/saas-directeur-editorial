# Studio — réponses tardives après navigation

18 octobre 2026. Périmètre : PR #204, base main
`d08fe0afe62f0ea209da239aeade0bd5f042d30d`.

Symptôme : une réponse réseau de l'histoire A peut arriver après ouverture
de B, ou après un aller-retour A → B → A. Vérifier le scénario avec des
données synthétiques et une promesse HTTP retardée, sans requête métier mutante.
Ne pas confondre ce défaut d'affichage avec une modification des données serveur.

La PR capture l'identifiant de l'histoire et le compteur `openRequest` avant
les requêtes de détail, réconciliation, relecture, historique, décisions et
polling. Succès et erreurs obsolètes sont ignorés. Le compteur invalide aussi
les réponses après déconnexion. Les contrôles de session restent obligatoires.
Le message HTTP 429 couvre désormais toutes les opérations, pas seulement le login.

La revue a reproduit le cas A → B → A encore présent dans les premières
gardes d'historique/décisions/polling : comparer seulement l'ID ne distingue
pas deux visites de la même histoire. Le compteur est désormais vérifié.

## Preuves et limites

Tests déterministes Node/V8 des fonctions réelles extraites de `studio.js` :
6 échecs avant la correction complémentaire ; 12/12 réussis après, sans skip.
Couverture : succès et erreurs A → B → A, déconnexion, réponse courante conservée.
DOM minimal simulé ; ces tests ne constituent pas un parcours navigateur.

```bash
node --check apps/web/studio.js
node --test browser_checks/test_studio_races.js
python -m unittest discover -s browser_checks -p test_studio_browser.py -v
python scripts/run_regression.py
```

Seules les deux commandes Node ont été exécutées dans cette revue isolée.
Le scénario Playwright A → B de la PR reste à exécuter dans un vrai Chromium.
La CI historique, PostgreSQL dédié et les contrats API restent à valider sur
le SHA final avant fusion. Aucun correctif serveur, migration, secret, service
ou déploiement PC modifié. Pas de relance automatique de génération.

Reprise : conserver la PR en brouillon tant que les contrôles requis échouent.
Le blocage GitHub Actions avant toute étape est distinct de ce défaut JS.
Retour arrière applicatif éventuel : release privée précédente préservée,
via le mécanisme de déploiement autorisé, jamais suppression des données.
