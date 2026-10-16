# Arvor Studio — Histoires et Conception

## Fonctionnalités ajoutées sur la branche de la PR #92

### Histoires
- Bibliothèque paginée à partir de `/studio/api/runs`, avec tuiles et filtre.
- Ouverture d'une histoire, synopsis, brief en lecture, scènes et personnages.
- Navigation histoire → scène → élément (narration, décor, palette, cadrage, émotion, sons, image_prompt).
- Profils personnages issus du casting Qwen et des scènes ; une fiche peut être complétée pendant la révision.
- Création via formulaire existant et nouvelle demande Qwen (idempotence conservée).
- Modification : `ReviewDecision(action=revise)` et optimistic locking sur `review_revision`.
- Les versions déjà approuvées sont révisables sans écraser le scénario précédent ; une nouvelle approbation reste obligatoire.
- Images via `/studio/api/runs/{uuid}/visuals` (contrôle de statut et affichage privé).
- Métadonnées `production_media` (vidéo, voix, sous-titres, manifeste) via `/studio/api/runs/{uuid}/media`. Le navigateur ne reçoit jamais les clés S3, bucket, credentials ni URL publique.
- Les données effectivement absentes ne sont pas inventées : un fichier seulement présent en dehors du catalogue audit n'est pas présenté comme disponible.

### Conception
- Epics et états depuis les issues GitHub portant `[EPIC-` ou `Epic`.
- PR et statut courant depuis l'API privée GitHub.
- Calendrier navigable calculé à partir d'événements datés : ouverture d'epic = développement ; ouverture/fusion PR = validation ; workflow PC réussi = production.
- Les pourcentages d'avancement ne sont pas inventés en l'absence de correspondances fiables entre issues et epics.
- Bouton d'autorisation de livraison disponible pour une PR **déjà fusionnée**, avec confirmation explicite et deuxième secret.
- La revue de PR et sa fusion restent dans GitHub (les auteurs ne peuvent pas approuver leur propre PR sur GitHub). Le bouton **n'approuve ni ne fusionne** le code.

## Configuration privée

Les variables sont illustrées dans `.env.example` et doivent rester dans la configuration privée, jamais dans les commits.

```dotenv
EDITORIAL_GITHUB_READ_TOKEN=<private fine-grained token with issues/pull-requests/actions read>
EDITORIAL_GITHUB_DELIVERY_WRITE_ENABLED=false
EDITORIAL_GITHUB_WRITE_TOKEN=<separate tightly scoped server-only token>
EDITORIAL_GITHUB_APPROVAL_SECRET=<random secret >=32 chars and distinct from web password>
```

Le token de lecture est indispensable au cockpit du dépôt privé. Sans token, le serveur répond 503 et l'interface explique que la configuration est requise.

Ne pas activer les écritures avant la validation du mécanisme avec un token limité au dépôt et autorisé à modifier les variables GitHub Actions et déclencher les workflows. Le code refuse toute autorisation de production sans :
1. Session HTTPS/localhost valide et origine + protection CSRF.
2. Confirmation `AUTORISER PC` et secret de production distinct du mot de passe de connexion.
3. `EDITORIAL_GITHUB_DELIVERY_WRITE_ENABLED=true` et variable GitHub `LOCAL_PC_ENABLED=true`.
4. PR déjà fusionnée sur `main`, SHA de fusion exact de 40 caractères et identique à la tête courante de `main`.
5. `regression.yml` terminée avec succès en événement `push` sur `main` pour le SHA exact.
6. Écriture de `LOCAL_PC_APPROVED_SHA`, puis `workflow_dispatch` de `local-delivery.yml` sur le SHA. Lancement **demandé** n'est pas preuve de livraison réussie.

En cas d'échec de déclenchement, une restauration de la valeur d'approbation précédente est tentée. Confirmer l'état de GitHub Actions avant toute nouvelle demande, car un incident réseau peut rendre le résultat incertain.

## Contrôles de recette

```bash
python -m unittest tests.test_studio_conception -v
python -m unittest tests.test_studio -v
node --check apps/web/studio.js
python -m py_compile apps/api/studio.py editorial/api.py editorial/store.py
# La CI Full regression utilise une base PostgreSQL jetable.
# Parcours Chromium :
STUDIO_BROWSER_TESTS=yes python -m unittest discover -s browser_checks -p 'test_studio_browser.py' -v
```

Parcours fonctionnels à vérifier : liste tuiles → histoire → scène → composant → fiche personnage ; création et relecture ; édition d'une version approuvée → nouvelle version en attente → validation ; calendrier PR et release ; déconnexion ; mobile ; jeton GitHub absent ; mauvais SHA ; régression rouge ; deuxième facteur incorrect ; workflow indisponible.

## Limites actuelles

- Pas de CRUD autonome pour des entités personnages/décors hors storyboard ; leurs modifications repassent par une révision globale Pydantic.
- Le brief (topic, public, durée...) est consultable mais non modifiable directement après création ; la durée du storyboard reste contrainte par le brief initial.
- Pas de lecteur audio/vidéo MinIO ni d'upload de voix/vidéo par l'interface : seules les métadonnées auditées sont exposées.
- GitHub fournit les états d'issue mais pas de progression fiable en pourcentage sans un modèle explicite de dépendances.
- L'app ne fusionne pas les PR. L'autorisation PC n'est opérationnelle que si les variables et permissions serveur sont préparées.
- Une PR en brouillon ne doit pas être fusionnée ou livrée avant régression réussie et décision humaine.
