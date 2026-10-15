# Lot 2 — provenance des images et recette privée

15 octobre 2026. Base de travail : PR #87, `9d1a1e444bc79a130f8e74bcacc49d26ef376baf`.
Ces évolutions sont du code à qualifier par CI, pas une installation PC.

## Provenance conservée

Chaque réservation d'image conserve dans `po_entity.content`, avec audit/outbox
dans la même transaction : scénario et scène, SHA du code si identifié par la
release, prompt exact privé et son empreinte SHA-256, paramètres HTTP effectivement
envoyés, instantané des personnages et empreinte de cet instantané. La réservation
recalcule le prompt sous verrou du run et refuse une identité de scène périmée.

Après réponse et écriture du fichier : dimensions, taille en octets, empreinte
SHA-256 du PNG, début/fin et durée monotone du rendu + stockage. Ce temps inclut
l'attente HTTP et l'écriture disque, pas la seule exécution GPU. Les empreintes
des repères personnages doivent rester identiques entre les scènes d'une même
version. Cela prouve la réutilisation des descriptions, pas la ressemblance
artistique des visages ou costumes.

Le contrat OpenAI-compatible de SD.cpp transmet seulement `prompt`, `n`, `size`
et `output_format`. Il ne rapporte pas le modèle exact ni la seed ; `GET /v1/models`
utilise même l'identifiant générique `sd-cpp-local`. Modèle et seed restent donc
`null`, avec `not_reported_by_image_contract`. Aucune fausse reproductibilité
n'est annoncée. L'API native SD.cpp, les seeds imposées, références images et LoRA
nécessitent un adaptateur et une qualification de la version installée ultérieurs.

Référence officielle consultée :
https://github.com/leejet/stable-diffusion.cpp/blob/master/examples/server/api.md

## Contrôle des images en lecture seule

Dans Studio → Personnages & images, « Vérifier les images et leur historique »
vérifie les fichiers déjà présents, leur empreinte, dimensions 512×512, taille,
durée connue et au moins deux événements audit/outbox. Aucune nouvelle génération.
Le contrôle PNG vérifie aussi les CRC des chunks, la fin du fichier et la
décompression bornée des lignes. Les PNG entrelacés sont déclarés non vérifiés
par ce contrôle ; aucun décodeur graphique complet n'est ajouté.
Les empreintes identiques entre scènes sont signalées pour revue humaine.

API privée : `GET /editorial/runs/{uuid}/visuals/verification?expected_scenes=3`.
La façade Studio utilise une session privée ; aucun Bearer n'est envoyé au JS.
Les anciennes images sans provenance sont affichables mais échouent au contrôle
complet : ne pas inventer ou rétroremplir leur durée et leur modèle.

CLI depuis la release autorisée, avec le token déjà injecté dans l'environnement
privé du processus (ne jamais le copier dans la commande ni dans un ticket) :

```bash
.venv/bin/python scripts/verify_image_receipts.py --run-id UUID_DU_RUN --expected-scenes 3
```

URL par défaut : loopback port 8000 ; surcharge privée via `EDITORIAL_API_URL`.
Code 0 = intégrité/traçabilité techniques conformes ; 2 = vérification incomplète.
**Aucun de ces codes ne signifie que le lot est accepté ou que Vulkan fonctionne.**
Le script émet uniquement le rapport borné de contrôle, sans prompt ni titre métier.

## Ressources et qualité : mesures explicitement indisponibles

`gpu_verified=false`, `vram_peak_bytes=null`, `human_visual_review_required=true`.
Le diagnostic du moteur expose également l'absence de preuve du modèle et de VRAM.
Les mesures doivent être relevées sur Windows pendant le vrai rendu avec les outils
adaptés au pilote ; ni les 8 Go annoncés ni la mémoire partagée ne constituent une
mesure de consommation. Aucun outil GPU tiers n'est installé par cette évolution.

## Échecs et reprise

Un timeout produit `image_provider_timeout`, un transport interrompu/HTTP 5xx
`image_provider_response_uncertain`, un refus HTTP `image_provider_rejected`.
Les états ambigus restent bloqués pour toute nouvelle génération automatique.
Si le moteur a rendu et que l'acquittement DB est perdu, le fichier est conservé
en privé : le supprimer pourrait casser un enregistrement déjà validé en base.
La procédure manuelle est dans [le runbook images](mco/IMAGE_GENERATION_RECOVERY.md).
Cette évolution ne propose ni bouton de rejeu ni réparation SQL automatique.

## Installation et retour arrière

Aucune nouvelle variable requise, dépendance, migration, téléchargement de modèle
ou configuration de service. Conservation du mode privé à un seul processus.
Activation PC soumise au SHA exact ; les dossiers médias restent hors release.
Retour arrière de code possible ; conserver les médias et les reçus additionnels.
Le lot 2 reste ouvert jusqu'au vrai rendu de trois images, mesure VRAM/durée,
contrôle technique et validation visuelle humaine.
