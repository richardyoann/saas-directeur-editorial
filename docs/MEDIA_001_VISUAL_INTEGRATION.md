# MEDIA-001 — Histoire → personnages → scènes → images privées

## État et périmètre

Ce lot ajoute une **intégration de base** : Qwen rédige l'analyse et le
storyboard (mécanisme déjà existant), avec un champ optionnel `cast` comportant
`name`, `appearance`, `personality` et `role`. Les anciens scénarios
conservent leur compatibilité sans `cast`. Le nouvel onglet **Personnages &
images** présente les personnages dédupliqués, leurs scènes et les prompts
visuels qui réutilisent l'apparence du personnage pour la cohérence.

**Qwen 2.5 3B en local est utilisé pour la rédaction de texte/JSON, pas pour
fabriquer des pixels.** Les images sont produites **uniquement après validation
humaine du scénario**, par une API distincte, locale/privée, compatible avec
`POST /v1/images/generations`. Une demande correspond à une seule scène. Un
échec ou résultat réseau ambigu est historisé mais jamais rejoué automatiquement.

### Exemple de fiche de personnage (fictif)

```json
{
  "name": "Le marin",
  "appearance": "Manteau rouge, barbe grise, bonnet de laine",
  "personality": "Prudent et courageux",
  "role": "Témoin de la légende"
}
```

Les champs de description ne sont **pas garantis** pour chaque sortie Qwen :
la fiche de secours contient seulement les noms et indices de scènes. La
qualité artistique et la cohérence entre images doivent être revues sur un
vrai modèle d'images. Aucun modèle d'image n'est installé par cette PR.

## Configuration PC privée — non appliquée par la PR

Le service de génération d'image doit être installé et démarré **séparément**,
avec son propre modèle et ses réglages GPU adaptés à la machine. L'intégration
ne suppose **ni ComfyUI installé, ni modèle Stable Diffusion opérationnel**.

Dans `~/editorial-runtime/private/runtime.env` (jamais dans Git) :

```dotenv
IMAGE_BASE_URL=http://127.0.0.1:8082
EDITORIAL_MEDIA_ROOT=/home/yoann_admin/editorial-runtime/media/generated
```

L'URL doit désigner une IP locale/privée (ou `localhost`) sans identifiants
dans l'URL, ni chemin supplémentaire. Le fournisseur doit accepter :

```http
POST /v1/images/generations
Content-Type: application/json

{"prompt":"...","n":1,"size":"512x512","output_format":"png"}
```

Et renvoyer un seul objet `data[0].b64_json` encodant un PNG valide
(≤4 Mio ; dimensions 1–2048 pixels). Ni réponse `url`, ni téléchargement
d'URL externe ne sont acceptés. Les fournisseurs qui requièrent un schéma
ComfyUI spécifique nécessitent un adaptateur futur ; on ne les prétend pas
compatibles avec ce contrat tant que testé.

Créer le répertoire privé **hors des releases immuables** en contrôlant
propriétaire et permissions : `0700` pour répertoires, `0600` pour fichiers.
Ne pas placer les médias dans `apps/web/` ni les exposer via un serveur statique.

## Parcours et traçabilité

1. `POST /editorial/runs` (Qwen) → `analysis` et `storyboard`, snapshots
   du prompt et de la sortie en PostgreSQL (déjà en place).
2. Revues humaines `analysis` et `storyboard` → statut `approved`.
3. `GET /editorial/runs/{uuid}/visuals` → personnages, profils optionnels,
   association aux scènes, prompts, statut des images, sans chemin de stockage.
4. `POST /editorial/runs/{uuid}/scenes/1/image` (Bearer privé) → réservation
   transactionnelle en `po_entity(kind=result)`, `type=scene_image_asset`.
   `audit/outbox` créés dans la même transaction. Génération image puis
   écriture privée, transition `generating → ready` ou `failed`.
5. `GET /editorial/runs/{uuid}/scenes/1/image` → PNG depuis l'API privée,
   uniquement si le scénario courant est approuvé et si l'asset correspond
   à la scène. Studio relaie la réponse sous cookie de session privée.
   Réponse `Cache-Control: no-store` ; aucun fichier exposé publiquement.

Les identifiants d'assets sont déterministes par scène et version de scénario.
Les versions révisées gardent leurs scènes et audit, et ne récupèrent pas une
image de la version précédente par erreur. Une requête identique après une
première génération ou un échec est refusée (HTTP 409), sans double facturation
ou rejeu implicite. Un statut `generating` persistant doit être investigué
avant un mécanisme **explicite** de réconciliation ultérieure.

Aucun changement du schéma SQL (reuse de `po_entity`, `po_audit`,
`po_outbox`) et aucun stockage d'image en JSONB. Le prompt visuel est
historisé en base : ne pas partager de dump ni captures de détails métier.

## Tests et limites de recette

```bash
python scripts/run_regression.py
node --check apps/web/studio.js
python -m unittest discover -s tests -p 'test_visuals.py' -v
```

Sur CI, les tests utilisent une API d'images simulée retournant un PNG miniature
et une base PostgreSQL 16 **jetable**, avec contrôle de l'authentification,
de l'approbation, de la persistance `po_entity`, de l'audit/outbox, de la
non-duplication et de la lecture des images par le tenant.

Cela valide **le contrat d'intégration**, pas un modèle génératif d'images
installé, la qualité graphique, la vitesse du GPU RX 580 ou la stabilité de
l'affichage sur téléphone. Aucun générateur d'images réel n'est utilisé dans la
CI ni depuis ce chat. La réalisation d'images avec un modèle local et la
recette PC doivent être exécutées sur la release explicitement autorisée,
avec preuve de version et limites mémoire/GPU.

**Retour arrière :** ne pas déployer ce SHA, ou restaurer l'ancienne release
du SaaS. Les médias privés sont conservés lors d'une réversion du code ; aucun
effacement automatique n'est effectué. Ne pas relancer un appel d'image ambigu
à l'aveugle.

Aucun montage vidéo, synchronisation de lèvres, piste audio générée, publication
réseaux sociaux ou entraînement automatique n'est prétendu livré par ce lot.
