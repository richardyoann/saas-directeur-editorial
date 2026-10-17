# ARVOR — Studio de production multi-agents et qualité critique (Lot 2)

**Statut au 17/10/2026 : code proposé sur branche/PR, pas encore validé ni déployé sur PC.** Base `main` : `d08fe0afe62f0ea209da239aeade0bd5f042d30d`.

## Périmètre effectivement codé

Le Studio privé propose un onglet **Équipe IA & critique** sur chaque histoire.
L'opérateur ouvre un storyboard **approuvé** de **75 secondes** et initie volontairement une préproduction. Aucun agent n'est lancé à l'ouverture de l'onglet.

L'orchestrateur Python exécute, un métier à la fois, sur le même fournisseur Qwen local :

| Ordre | Rôle | Livrable |
| --- | --- | --- |
| 1 | Scénariste | Rythme, narration, dramaturgie, contrainte 75s |
| 2 | Directeur artistique | Bible visuelle, continuité des personnages |
| 3 | Cadreur | Plans, raccords, mouvements de caméra |
| 4 | Animateur | Animation réalisable d'images, effets |
| 5 | Ingénieur du son | Voix, mixage, ambiances |
| 6 | Monteur | Timeline 75s, export, transitions, sous-titres |
| 7 | Critique en chef | Avis critique textuel indépendant et corrections attribuées |

**Ces rôles ne sont pas sept modèles entraînés séparément.** Ce sont des contrats/prompts spécialisant séquentiellement le Qwen déjà installé. Il n'y a pas de fine-tuning et aucun rôle ne crée ou publie encore de MP4.

Le critique évalue sept critères pondérés sur 100. Seuil de préproduction : **>=90/100**, **>=80 % pour chaque critère**, aucun défaut bloquant ni demande de correction. Les scores LLM sont subjectifs ; l'algorithme Python est seulement le **contrôle déterministe des seuils**, non une garantie de bonne qualité visuelle.

Une note insuffisante doit identifier au moins un métier responsable ; un avis négatif sans correctif actionnable est rejeté. L'opérateur peut déclencher une correction ciblée : seuls le métier choisi et les étapes aval sont recalculés, en conservant l'historique de toutes les versions. **Au maximum deux cycles de correction** supplémentaires. Après succès, l'état est `ready_for_human_review`, pas « publié » ni « rendu validé ».

## Sécurité et cohérence

- Réutilise l'identité privée issue de `get_identity` ; aucun tenant/acteur ne vient du navigateur. Le Studio relaie les appels derrière sa session HttpOnly, contrôle d'origine et jeton CSRF, sans exposer de Bearer au JavaScript.
- PostgreSQL `po_entity` existant, catégories `result` et métadonnées sous `treatment`, sans nouvelle table ni migration. Chaque mutation est effectuée dans une transaction avec audit et outbox via `PostgresStore._write`. Les sources approuvées sont verrouillées et empreintées, avec contrôle de révision.
- Génération **sur action explicite**, une étape par POST ; claim atomique avant HTTP Qwen et contrôle de révision optimiste, empêchant le rejeu d'une étape déjà réclamée.
- Timeout, crash ou coupure : le résultat reste bloqué ; aucune relance automatique. Une réconciliation explicite après 10 minutes marque seulement l'incertitude. Pour corriger un cas incertain, créer une nouvelle version après diagnostic humain. Aucun script ne supprime de traces.
- Chaque rôle reçoit le document approuvé et les livrables textuels précédents comme **données non fiables** ; sortie JSON Pydantic stricte, `finish_reason=stop` requis. Pas d'outils système accordés à Qwen, pas de scraping ni d'appel public.
- Le critique textuel **ne voit aucun pixel et n'écoute aucun audio** : ne pas interpréter la note comme évaluation du MP4. Un examen humain visuel et audio reste obligatoire.
- Aucun changement aux secrets, à MinIO, aux volumes, au modèle GGUF, aux services existants, aux workflows de déploiement ou au paramètre du worker.
- Les livrables métier et historiques contiennent des informations privées : GET/auth seulement, aucune copie dans GitHub, Slack ou les journaux applicatifs.

## Contrôles du véritable rendu

`scripts/critic_render.py` est un contrôle **hors production et lecture seule**, pour un épisode déjà exporté via `scripts/render_episode.py`.

Depuis un répertoire privé contenant `episode.mp4`, `receipt.json` et `narration.srt` :

```bash
.venv/bin/python scripts/critic_render.py /chemin/prive/de/l-export
```

Vérifie empreinte SHA-256 déclarée dans le reçu, durée de 75 secondes, 720×1280, 24 i/s, présence d'une piste vidéo et audio, sous-titres présents, et sécurité minimale des chemins. Code de sortie 0 : ces propriétés vérifiées ; 2 : rejet. La sortie est une liste de codes fixes, **sans contenus médias ni chemins privés**.

Le rendu lui-même n'est pas produit par ce script. **Aucun examen de qualité des voix, de lip-sync, des mouvements, des visages, de l'articulation narrative ou de la musique** n'est actuellement possible sans moteur multimodal et recette dédiée.

## API privée (après livraison explicite)

- `POST /editorial/runs/{id}/production` : crée ou retrouve un dossier idempotent lié à la révision approuvée, sans Qwen.
- `GET /editorial/runs/{id}/production` : état, livrables de préproduction et score.
- `POST /editorial/runs/{id}/production/advance` : **exactement un rôle**, corps `{"expected_revision":0}` (utiliser la révision renvoyée par GET, jamais une constante).
- `POST /editorial/runs/{id}/production/revise` : `{"expected_revision":N,"target_role":"cinematographer"}`, seulement si le Critique l'a demandé.
- `POST /editorial/runs/{id}/production/reconcile` : marquer une étape déjà incertaine après 600s ; jamais la relancer.
- `GET /editorial/runs/{id}/production/history` : snapshots privés immuables.

Les équivalents `/studio/api/runs/...` sont réservés aux sessions navigateur, avec CSRF pour les POST.

## QA à exécuter

Depuis une **copie de travail séparée**, jamais sur la release en service :

```bash
cd ~/saas-directeur-editorial-github
git fetch origin
git worktree add --detach ~/arvor-crew-check origin/feature/production-crew-quality-gate-20261017
cd ~/arvor-crew-check

~/editorial-runtime/current/.venv/bin/python -m unittest \
  tests.test_production_crew tests.test_render_critic -v
node --check apps/web/studio.js
```

Les tests PostgreSQL ne doivent s'exécuter que sur une base **jetable**, jamais sur le `PO_DATABASE_URL` de production :

```bash
PO_TEST_DATABASE_URL='postgresql://...BASE_TEST_JETABLE...' \
PO_ALLOW_TEST_MIGRATION=yes \
~/editorial-runtime/current/.venv/bin/python -m unittest \
  discover -s tests -p 'test_production_postgres.py' -v
```

Valider ensuite le parcours réel avec un storyboard de **test**, le serveur Qwen réel, une instance PostgreSQL de test, les refus (401/403/409), une correction ciblée, l'historique/audit/outbox et les parcours navigateur (desktop/mobile) ; puis appliquer seulement le déploiement privé normalement approuvé au **SHA complet exact**.

## Limites connues et suite du Lot 2

1. Le modèle Qwen peut ne pas respecter le schéma demandé ; le rôle reste bloqué, aucun fallback permissif. Les 7 appels consécutifs peuvent être lents sur la RX 580 ; **aucun débit GPU mesuré**.
2. L'analyse critique audiovisuelle **multimodale** des vrais fichiers (images, audio et vidéo) reste à faire ; il faudra un moteur de vision/audio et des tests de qualité.
3. Les rôles ne lancent pas encore `sd.cpp`, Piper ni FFmpeg, et la vidéo finale n'est pas assemblée automatiquement par le pipeline de rôles. La CLI FFmpeg existante reste séparée.
4. Les résultats de QA du nouveau SHA sont **inconnus** tant que GitHub Actions ne redémarre pas ou que les tests locaux n'ont pas été exécutés et documentés. Le quota GitHub Actions est épuisé. Aucun faux succès ni skip ne vaut validation.
5. Ce livrable n'établit pas une qualité « > 90 % » perceptuelle ; c'est un dispositif de triage de préproduction avec validation finale humaine.

**Aucune MEP PC autorisée par la création de la PR.**
