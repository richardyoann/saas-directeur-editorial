# Arvor — parité avec la référence visuelle (16 octobre 2026)

## Objectif
Reproduire dans le Studio privé local les écrans montrés dans les captures utilisateur :
**Mes histoires**, **Journal de création**, **Administration**.
Le site chatgpt.site est une référence visuelle et fonctionnelle, pas une source de données et ne doit pas être considéré comme connecté à l'environnement PC.

## Constat vérifié
- SHA livré sur PC : 1aeddcb8e496510034a272484f9bde955fd11fb0.
- L'interface locale actuelle affiche Histoires, Conception et Nouvelle histoire.
- Le serveur FastAPI expose déjà un endpoint de lecture de données GitHub : `/studio/api/conception`.
- L'interface de référence présente en plus une navigation Administration, un journal, une vue des epics/stories, PR, commits, agenda.
- Les illustrations de démonstration de la référence ne prouvent pas l'existence de médias privés en base.

## Lot UI-1 — Shell et navigation
- Identité Arvor vert profond / beige, typographies et proportions de la maquette.
- Barre latérale : Mes histoires, Journal de création, Administration.
- Routes / vues accessibles et correctes après rafraîchissement et navigation navigateur.
- Responsivité desktop + mobile et navigation clavier.
- Aucun faux badge d'état ni compteur non issu des vraies données.

## Lot UI-2 — Histoires et mémoire
- Bibliothèque issue de l'API `/studio/api/runs`, filtres, recherche, détail, création.
- Journal d'événements métier historisés et vérifiables : versions, prompts, traitements; ne pas fabriquer les événements à partir des seules dates des histoires.
- Visuels de référence affichés uniquement comme démonstration clairement marquée; médias réels par endpoint privé.
- Gestion explicite des états vide, chargement, erreur et pagination.

## Lot UI-3 — Cockpit administration
- Pages : Vue d'ensemble, Epics et stories, Pull requests, Commits, Agenda (jour / semaine / mois).
- API serveur GitHub read-only et authentifiée; pas de token dans le navigateur.
- Côté GitHub : lister issues/PR, commits, statuts CI; relier PR, epic, SHA avec preuves.
- Distinguer statut git, résultat CI, résultat de livraison PC; ne jamais inférer que « CI OK = PC livré ».
- Indicateurs OK/KO/en cours/non vérifié, horodatages explicites; pagination et fraîcheur de collecte.
- Aucune action de livraison depuis le Studio; consentement explicite sur SHA et GitHub Actions existants.

## Sécurité et données
- Conserver `/studio` avec sessions et CSRF existants, filtrage tenant, sorties DOM sûres.
- Aucune migration/suppression de PostgreSQL/MinIO; aucune exposition du GITHUB_TOKEN.
- Ne pas mélanger la maquette hébergée avec les données privées du PC.

## Recette / DoD
1. Les trois rubriques sont visibles et opérationnelles sur localhost:8000/studio.
2. Une histoire existante et sa structure sont lisibles, une histoire créée reste disponible après rechargement.
3. Le journal affiche de vrais événements, les filtres ne mentent pas et un traitement réel renvoie à sa trace.
4. L'administration affiche des informations GitHub récupérées côté serveur, avec commits et calendrier.
5. Un état de PR KO apparaît en rouge, OK en vert, inconnu en neutre.
6. CI régression + sécurité + tests navigateur + contrôle API passent.
7. Livraison par SHA exact, reçu `last_delivery.json`, test `/ready`, `/studio` et parcours réel.
8. Pas de merge tant que les critères ci-dessus ne sont pas satisfaits.

## Implémentation vérifiable dans la PR #97
- `apps/web/arvor_reference.css` : styles et responsivité du shell de référence.
- `apps/web/arvor_reference.js` : journal privé avec traces réelles, cockpit et calendrier GitHub.
- `apps/api/studio.py` : `/studio/api/conception/commits` et `/studio/api/conception/ci` + issues; endpoints read-only/session.
- `apps/web/studio.js` : images depuis la route privée par histoire, avec fallback neutre si absentes.
- `tests/test_arvor_reference.py` : tests contractuels, authentification et exposition d'actifs.
- `browser_checks/test_studio_browser.py` : parcours navigateur Journal / Administration.
- `.github/workflows/regression.yml` : vérification JS du module complémentaire.

La comparaison est **fonctionnelle et esthétique**, pas pixel-perfect. Les images présentes sur chatgpt.site sont des visuels de référence; aucun média utilisateur n'est fabriqué. Si aucune image n'est enregistrée pour une scène, la carte reste neutre.

Le journal expose le détail des étapes et décisions d'une histoire sur demande, et non un flux global exhaustif. La liste initiale est limitée aux 50 dernières histoires chargées. L'API GitHub est paginée de façon bornée et le client signale les limites.

## Exploitation après future livraison PC
1. Vérifier que `EDITORIAL_GITHUB_REPOSITORY=richardyoann/saas-directeur-editorial` est défini **dans la configuration privée persistante** du serveur.
2. Si l'administration GitHub est souhaitée, configurer `EDITORIAL_GITHUB_READ_TOKEN` sur l'hôte, avec permissions de lecture minimales. Ne jamais publier sa valeur dans les logs, GitHub, captures ou navigateur.
3. Ouvrir `http://localhost:8000/studio` : contrôler les trois vues et un vrai détail d'histoire, et les états GitHub absent/accessible.
4. Une nouvelle mise en service PC exige validation explicite du SHA complet et preuve réelle via `diagnose_runtime.py` (CI verte ne suffit pas).

## Critères avant fusion (code)
Régression Python 3.12/3.14 avec PostgreSQL jetable, audit de dépendances, parcours Chrome et tests de contrat tous réussis sur la tête de PR, sans bypass de tests. Vérifier manuellement les données GitHub privées lorsque le token est disponible.

## Critères après livraison PC (opération distincte)
SHA active/reçu cohérents, HTTP 200 /ready et /studio, navigation validée par le propriétaire sur son PC. Ne pas confondre fusion et déploiement.
