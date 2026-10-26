# Arvor — découpage proposé des modules média

Date : 18 octobre 2026. Base inspectée : `1aeddcb8e496510034a272484f9bde955fd11fb0`.
Statut : plan initial ; frontières média désormais implémentées (voir la section finale et docs/ARCHITECTURE_MEDIA.md), sans acceptation métier ni MEP.
Validation : graphe existant interrogé et contrats sources relus ; aucun test exécuté pour ce document. Aucun déploiement, migration ou configuration runtime modifiée. Project privé non consultable avec le connecteur disponible. AGENTS.md préexistant préservé.

## Décision proposée

Conserver le monolithe et les processus actuels. Extraire le cas d’usage de génération d’image de la route HTTP, puis séparer règles pures, contrats et adaptateurs. Aucun microservice supplémentaire, nouvelle file ou nouvelle dépendance requis.

## Fichiers cibles et responsabilités

| Module cible | Responsabilité et éléments existants à déplacer |
|---|---|
| `editorial/media/contracts.py` | Types de réservation, résultat PNG, reçu de stockage, erreurs métier et Protocol des ports ; sans FastAPI, psycopg, HTTPX ni boto3. |
| `editorial/media/rules.py` | `characters`, `image_prompt`, `image_provenance`, paramètres/version du contrat ; fonctions pures sur un snapshot approuvé. |
| `editorial/media/png.py` | Validation binaire et bornes PNG ; sans réseau ni stockage. |
| `editorial/media/application.py` | Cas d’usage `GenerateSceneImage` : plan, capacité, préflight, réservation, rendu, stockage, finalisation et reprise. |
| `infrastructure/private_endpoints.py` | Politique d’URL privée extraite de `private_image_url` ; partagée par serveur image et S3, sans dépendance vers editorial. |
| `infrastructure/images/sdcpp.py` | Adaptateur du port ImageRenderer ; contrat HTTP actuel `/v1/images/generations`, durée bornée, refus des redirections et décodage base64. |
| `infrastructure/media/filesystem.py` | Chemins privés, création exclusive, lecture et conservation des fichiers de reprise. |
| `infrastructure/media/s3.py` | Adaptateur boto3, références privées, PUT conditionnel et intégrité ; logique existante de media_storage. |
| `infrastructure/persistence/media_repository.py` | Extraction progressive des méthodes média de PostgresStore, contrôles sous verrou et écritures via pilotage.audit. |
| `apps/api/media.py` | Routes média et mapping explicite erreurs → statuts HTTP ; identité issue de l’authentification. |
| `apps/api/dependencies.py` | Assemblage des adaptateurs, configuration et clients ; durée de vie et capacité compatibles avec le processus actuel. |

Les noms de modules ci-dessus sont des cibles proposées, pas des fichiers annoncés existants. `editorial/visuals.py`, `editorial/media_storage.py` et les méthodes de PostgresStore restent temporairement des façades de compatibilité ; leur suppression attend la migration des CLI et des tests.

## Interfaces proposées

Signatures illustratives ; types immuables et propriétés précisées ci-dessous.

```python
class MediaRepository(Protocol):
    def plan(self, identity: Identity, run_id: UUID) -> VisualPlan: ...
    def reserve(self, identity: Identity, request: ImageRequest,
                expected: SceneSnapshot) -> ImageReservation: ...
    def complete(self, identity: Identity, reservation: ImageReservation,
                 result: ImageCompletion) -> ImageResult: ...
    def record_failure(self, identity: Identity, reservation: ImageReservation,
                       failure: MediaFailure) -> None: ...

class ImageRenderer(Protocol):
    async def render(self, request: RenderRequest) -> RenderedPng: ...

class MediaStorage(Protocol):
    def preflight(self, location: AssetLocation) -> None: ...
    def save(self, location: AssetLocation, png: RenderedPng) -> StoredAsset: ...
    def load(self, location: AssetLocation,
             reference: StorageReference | None) -> bytes: ...
    def acknowledge(self, saved: StoredAsset) -> None: ...

class GenerateSceneImage:
    async def execute(self, identity: Identity,
                      request: ImageRequest) -> ImageResult: ...
```

- `Identity` : tenant et acteur provenant exclusivement de l’authentification ; aucun champ tenant/acteur libre dans ImageRequest.
- `ImageRequest` : run_id et scene_number, mêmes contraintes qu’aujourd’hui.
- `SceneSnapshot` : scene_id attendu et prompt exact lu ; reserve recharge l’état sous verrou, recalcule les règles pures et refuse toute divergence. L’état approuvé et le scénario courant restent vérifiés dans la transaction.
- `ImageReservation` : asset_id déterministe existant, run_id, scene_id, scenario_id, prompt et provenance capturés sous verrou. Le moteur reçoit ce snapshot réservé.
- `RenderRequest` : prompt et paramètres actuels, sans modèle ou seed inventés. `RenderedPng` : bytes validés, dimensions, SHA256 et taille.
- `StoredAsset` : référence privée optionnelle, handle opaque de reprise et nécessité d’acquittement. Aucun Path, bucket, clé ou secret dans la réponse publique.
- `acknowledge` : nettoyage du fichier temporaire de reprise après confirmation DB ; jamais suppression du média durable. Échec de nettoyage après succès DB ne transforme pas le succès en erreur.
- `MediaFailure` : code normalisé et certitude du résultat ; pas d’exception brute. Préserver les codes, outcome_uncertain et représentations persistées actuels.
- `MediaCapacity` : port injecté de réservation de capacité, libéré dans finally ; première implémentation conserve la portée processus actuelle. Une capacité partagée n’est pas introduite implicitement.

Les opérations psycopg, disque et boto3 restent synchrones et sont déportées hors de la boucle asyncio par le service applicatif. Le client HTTPX reste partagé, créé au lifespan et fermé par le point d’assemblage.

## Séquence et invariants

1. La route authentifie, valide run/scene et appelle le service ; elle traduit les erreurs en HTTP selon le comportement actuel.
2. Le service vérifie la configuration et acquiert la capacité ; aucun nouveau travail si la capacité manque.
3. Il lit le plan et effectue le préflight du stockage avant réservation.
4. `reserve` recharge le traitement sous verrou, vérifie approuvé/non périmé, scène et prompt ; crée exactement un asset avec mutation, audit et outbox dans la même transaction.
5. Après commit, le moteur est appelé une seule fois puis le PNG est stocké. Aucun verrou SQL maintenu pendant réseau ou stockage.
6. `complete` exige la réservation encore generating et le scénario courant approuvé ; il finalise métadonnées/référence et audit/outbox atomiquement.
7. Le fichier de reprise n’est acquitté qu’après succès DB confirmé. Timeout, perte d’acquittement ou exception inattendue ne provoquent ni régénération ni suppression du média.
8. Une erreur connue du moteur/stockage est enregistrée si possible ; perte d’acquittement DB reste incertaine et exige réconciliation. La capacité est toujours libérée.

Le stockage, le moteur et PostgreSQL ne forment pas une transaction distribuée. Le découpage conserve les mécanismes de reprise existants, sans prétendre supprimer les états partiels.

## Dépendances autorisées

`apps.api → application → contracts/rules/png` ; `infrastructure → contracts/rules/png` ; le point d’assemblage connaît les adaptateurs. Le domaine ne réimporte ni apps.api ni les adaptateurs concrets. L’adaptateur PostgreSQL peut utiliser les règles pures à l’intérieur de sa transaction : déplacer ce calcul hors verrou affaiblirait la protection actuelle.

Le fournisseur texte quitte ensuite `apps/api/llama_provider.py` pour `infrastructure/llm/llama.py`, derrière un port neutre. Cette étape est distincte du refactoring média ; préserver signatures, limites et sémaphore existants jusqu’à migration complète.

## Migration en quatre PR révisables

IDs ci-dessous locaux au plan, sans création d’issues ni acceptation Project implicite.

| ID | Périmètre | Critère concret et preuve attendue |
|---|---|---|
| ARCH-MEDIA-01 | Politique URL, règles pures et PNG ; façades compatibles | Cycle visuals/media_storage supprimé dans les imports ; tests URL, PNG, prompts et provenance inchangés réussis. |
| ARCH-MEDIA-02 | Ports, service applicatif et route mince ; PostgresStore adapté sans modification SQL | Même route/statuts, mêmes données publiques et codes d’erreur ; tests de concurrence et de panne aux frontières ci-dessous réussis. |
| ARCH-MEDIA-03 | Adaptateurs explicites et extraction dépôt média | Transactions CRUD/audit/outbox, IDs déterministes et références JSONB compatibles ; tests PostgreSQL sur cible dédiée sans skip. |
| ARCH-LLM-01 | Fournisseur texte dans un package neutre | Service/worker sans import vers apps.api ; contrats texte et tests historiques conservés. Peut avancer indépendamment après stabilisation des interfaces. |

Pas de nouvelle migration ni modification des variables ou unités de déploiement prévue. Si cette hypothèse change, mettre à jour scripts/configuration/runbooks dans la même PR. Chaque PR recalcule graphify, consigne SHA exact, commandes, résultats et limites ; preuves non transférables automatiquement à un SHA ultérieur. Toute activation PC reste soumise à validation humaine du SHA exact.

## Validation à exécuter lors de l’implémentation

Réutiliser les tests existants ; ajouter seulement les cas de frontière nécessaires : scénario modifié entre plan et réservation ; double réservation concurrente ; échec préflight sans asset réservé ; un seul appel moteur lors d’un timeout ; upload incertain sans suppression/rejeu ; commit DB confirmé ou acquittement perdu avec fichier conservé ; nettoyage échoué après succès DB ; libération de capacité sur toutes les sorties. Préserver les tests de refus des URL publiques, redirections, dépassements de taille, mauvais tenant et références altérées.

Exécuter les tests historiques Linux, pilotage/test_*.py, PostgreSQL dédié et parcours navigateur image. Les mocks ne prouvent ni MinIO réel ni rendu GPU. Une éventuelle recette privée réelle est distincte et ne déclenche aucune MEP ou acceptation éditoriale automatique.

Reprise du refactoring : petites PR sans migration de données, façades conservées puis retirées après inspection des consommateurs. Un retour de code prépare une release antérieure ; son activation demeure une MEP à autoriser, avec vérification préalable de compatibilité des références média. Aucun effacement d’asset pour revenir en arrière.

## Frontières appliquées — 18 octobre 2026

L’extraction suivante est réalisée sur la branche demandée, dans la PR #208 : service GenerateSceneImage/ReadMedia et ports dans editorial/media, dépôt SQL média dans infrastructure/persistence, adaptateurs rendu/fichiers/S3 distincts, routes et composition dans apps/api. Les façades historiques délèguent aux propriétaires sans dupliquer les règles. media_rules reste le module pur canonique plutôt que multiplier les déplacements. La correction de concurrence approval/finalization est couverte par un test PostgreSQL. Voir [l’architecture implémentée, diagrammes et limites](../ARCHITECTURE_MEDIA.md). Aucune fusion ni MEP ; contrôles finaux liés au SHA dans la PR. Le fournisseur texte reste hors du lot média.
