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
- Calendrier navigable calculé à partir d'événements datés : création d'epic, ouverture/fusion de PR et contrôle technique PC réussi. Ces événements ne prétendent pas prouver une mise en production.
- Les pourcentages d'avancement ne sont pas inventés en l'absence de correspondances fiables entre issues et epics.
- Le cockpit est strictement en lecture seule pour GitHub. Il n'écrit aucune variable Actions et ne déclenche aucun workflow.
- La revue, la fusion et l'autorisation d'une livraison restent hors de Studio. La livraison utilise le mécanisme exact-SHA documenté dans `docs/AUTONOMOUS_DELIVERY.md`.

## Configuration privée

Les variables sont illustrées dans `.env.example` et doivent rester dans la configuration privée, jamais dans les commits.

```dotenv
EDITORIAL_GITHUB_READ_TOKEN=<private fine-grained token with issues/pull-requests/actions read>
```

Le token de lecture est indispensable au cockpit du dépôt privé. Sans token, le serveur répond 503 et l'interface explique que la configuration est requise.

Le point de terminaison historique `POST /studio/api/conception/pulls/{pr}/deliver` est conservé uniquement pour compatibilité et répond toujours 403 après les contrôles de session, d'origine et de CSRF. Cette mise en échec explicite empêche tout état ambigu après timeout, double requête ou validation concurrente. Studio ne doit recevoir aucun token GitHub en écriture.

Une livraison privée est autorisée uniquement par le mécanisme exact-SHA décrit dans `docs/AUTONOMOUS_DELIVERY.md`, après revue documentée et CI réussie. Un lancement demandé, un workflow ignoré ou un contrôle technique vert ne constituent jamais à eux seuls une preuve de livraison métier.

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

Parcours fonctionnels à vérifier : liste tuiles → histoire → scène → composant → fiche personnage ; création et relecture ; édition d'une version approuvée → nouvelle version en attente → validation ; calendrier PR et contrôles PC ; déconnexion ; mobile ; jeton GitHub absent ; endpoint de livraison Studio refusé sans aucun effet GitHub.

## Limites actuelles

- Pas de CRUD autonome pour des entités personnages/décors hors storyboard ; leurs modifications repassent par une révision globale Pydantic.
- Le brief (topic, public, durée...) est consultable mais non modifiable directement après création ; la durée du storyboard reste contrainte par le brief initial.
- Pas de lecteur audio/vidéo MinIO ni d'upload de voix/vidéo par l'interface : seules les métadonnées auditées sont exposées.
- GitHub fournit les états d'issue mais pas de progression fiable en pourcentage sans un modèle explicite de dépendances.
- L'app ne fusionne pas les PR et ne déclenche aucune livraison. L'autorisation PC reste un processus exact-SHA externe au Studio.
- Une PR en brouillon ne doit pas être fusionnée ou livrée avant régression réussie et décision humaine.
