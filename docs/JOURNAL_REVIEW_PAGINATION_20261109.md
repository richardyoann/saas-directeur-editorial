# Pagination des décisions du journal

Le journal charge d'abord les 50 décisions les plus récentes. Quand la réponse fournit des révisions valides, le bouton **Charger les décisions plus anciennes** demande la page suivante avec le curseur exclusif `before_revision` (révision minimale de la page reçue). Les décisions déjà chargées sont conservées et les doublons par révision sont écartés. Une page de moins de 50 décisions termine la pagination.

Si la requête d'une page échoue, les décisions visibles et le curseur restent en place afin que l'utilisateur puisse réessayer. L'interface affiche un avertissement générique sans exposer le détail de l'erreur du service. Si une page complète ne permet pas de calculer un curseur valide ou ne fait pas avancer celui-ci, la pagination s'arrête avec un avertissement plutôt que de boucler.

## Validation reproductible

Depuis la racine du dépôt :

```sh
node tests/js/journal_review_pagination.test.cjs
```

Le test simule deux pages (50 puis 10 décisions), vérifie le curseur `before_revision=11`, l'absence de perte ou de doublons, l'échec puis la reprise d'une page, et l'accès à la décision la plus ancienne via la pagination locale.

Pour cette révision, ce scénario a été exécuté avec Node VM sur les fonctions `loadJournal`, `loadOlderJournalReviews` et `renderJournal` extraites de `apps/web/arvor_next.js` à la tête de la PR. Le service privé est simulé ; aucune donnée métier ni base de production n'est utilisée. Cette preuve ciblée ne remplace pas la suite complète, Chromium, les contrats PostgreSQL/isolation tenant, la revue indépendante ni les statuts CI au SHA final.

Aucun changement d'installation, de configuration, de migration ou de déploiement n'est inclus. Retour arrière : rétablir la version précédente de `apps/web/arvor_next.js` et retirer le test et ce document dans un commit de revert ; aucune donnée n'est modifiée.
