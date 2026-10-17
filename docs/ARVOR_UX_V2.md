# Arvor Studio — Refondre sans casser (17 octobre 2026)

## Périmètre
Refonte de l'interface privée **/studio/next**, sans modifier **/studio** (production locale), ni l'API, la base PostgreSQL, MinIO, les secrets, la CI/CD ou les contrats métier.

## Principes
- Navigation latérale vert profond, surfaces neutres, typographie éditoriale sobre et cohérente.
- Grilles, cartes et états actifs lisibles; éléments tactiles >= 42px; focus clavier et préférence de réduction des animations préservés.
- Composants existants uniquement; pas de framework, CDN, police distante ni JavaScript tiers.
- Cartes d'histoires et compteurs liés aux données de l'API; recherches sans résultat explicitement identifiées.
- Journal: la date de création est une **métadonnée**, pas une preuve de log des prompts/révisions. Les traces réelles sont accessibles dans « Historique IA » par histoire.
- La nouvelle vue ne promet pas la production de vidéos, d'images ou de voix si les pipelines correspondants ne sont pas opérationnels.

## Recette à exécuter sur branche/PR
1. Lancer les tests de régression et les tests navigateur du Studio; contrôler la session et les protections CSRF.
2. À /studio/next, parcourir bibliothèque, filtres, recherche, zéro résultat et création réelle.
3. Ouvrir une histoire : synopsis, scène, médias et historique; vérifier rafraîchissement et erreurs réseau.
4. Dans Journal, ouvrir l'historique d'une histoire; vérifier que les prompts rendus proviennent de l'API authentifiée et jamais de données de démonstration.
5. Dans Administration : vérifier issues, PR, commits, calendrier et distinction CI / livraison PC.
6. Valider desktop 1440/1024, tablette 768, mobile 390; clavier Tab/Échap/Ctrl+K, contraste et préférences de mouvement.

## Livraison
PR non fusionnée par défaut. La livraison sur PC est une étape séparée qui exige validation du **SHA complet**, workflow autorisé, reçu de livraison et vérification du runtime. Ne pas assimiler CI verte et déploiement effectif.
