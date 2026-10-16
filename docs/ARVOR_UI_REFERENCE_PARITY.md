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

## Avancement
Cadrage technique établi. **Fonctionnalités à implémenter et tester.**
Une tentative de modification du shell a été annulée car la modification JS associée n'a pas pu être transmise; l'interface existante a été restaurée sur la branche.
