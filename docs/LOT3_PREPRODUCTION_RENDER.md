# Lot 3 — relier la préproduction au rendu local

## Fonction disponible

`scripts/render_production.py` effectue une tentative explicite :
snapshots de scénario/préproduction → manifeste de montage → FFmpeg →
contrôle technique MP4 et SRT. Les PNG doivent déjà exister ; la voix WAV peut être fournie ou produite par une commande locale Piper séparée, après relecture.

Ce chemin est **hors ligne**. Il ne lit pas PostgreSQL, ne lance ni Qwen,
ni sd.cpp, n'envoie rien à MinIO et ne publie rien.
Il ne modifie ni sessions de production, ni historique métier.
Le lot 3 reste en cours.

## Conditions d'entrée

L'opérateur fournit deux snapshots privés issus de la même histoire :
- `run` : réponse de lecture du run éditorial approuvé, avec `id`,
  `review_revision`, `brief` et `storyboard`.
- `production` : réponse GET de sa préproduction, avec `stale: false`,
  phase `ready_for_human_review`, les sept sorties et la critique.

Les durées et narrations du manifeste sont reprises du storyboard validé,
pas du texte libre des spécialistes. Durée actuelle : exactement 75 s.
Le code réutilise les contrats Brief/Storyboard, SpecialistOutput/CriticOutput
et le contrôle qualité existant : >=90/100, >=80 % par critère, sans défaut
bloquant ni demande de correction. Une propriété `quality.passed` reçue
n'est pas une preuve : le score est recalculé.

Les IDs run/session, révision, snapshot source et empreinte canonique sont
comparés ; sessions incomplètes, actives, périmées ou incohérentes refusées.
Les images sont associées explicitement aux positions 1 à N des scènes,
avec le même nombre d'entrées. Une voix WAV couvrant 75 s à 0,25 s près
est requise par ce pipeline, même si l'ancienne CLI permet une vidéo muette.

**Limite d'autorité :** un JSON local peut être modifié. Ces vérifications
détectent les incohérences mais ne prouvent ni l'origine en base,
ni l'identité de l'approbateur, ni les droits du tenant. Cette CLI ne doit
pas être exposée comme endpoint web ou moyen d'approbation SaaS.
La relecture est une déclaration de l'opérateur sur les fichiers fournis.
La fraîcheur du run en base n'est pas recontrôlée pendant l'encodage.

## Préparer le bundle privé

Ne jamais placer les snapshots ou médias métier dans Git ou les logs.
Les récupérer via les lectures privées existantes et les conserver dans
un dossier de travail accessible seulement à l'opérateur.

Exemple de construction depuis `run.json` et `crew.json` déjà exportés :

```python
import json
from pathlib import Path

root = Path("/chemin/prive/pilote")
run = json.loads((root / "run.json").read_text(encoding="utf-8"))
crew = json.loads((root / "crew.json").read_text(encoding="utf-8"))
count = len(run["storyboard"]["scenes"])
bundle = {
    "schema_version": 1,
    "run": run,
    "production": crew,
    "media": {
        "images": [{"scene_index": i, "image": f"scene-{i}.png"}
                   for i in range(1, count + 1)],
        "voice": "voice.wav",
    },
}
(root / "bundle.json").write_text(
    json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
```

Ne pas changer les statuts ou scores pour franchir un refus.
Relire le scénario, la critique, les images et la voix, puis :

```bash
python scripts/render_production.py \
  /chemin/prive/pilote/bundle.json \
  /chemin/prive/pilote/medias \
  /chemin/prive/pilote/rendu-01 \
  --confirm-human-review
```

Python/dépendances du projet et FFmpeg/ffprobe requis. Aucun composant
n'est installé par cette commande. Parent de destination existant.
Destination neuve, créée exclusivement en mode 0700. Médias relatifs
confinés au répertoire fourni ; liens symboliques refusés. Même limite
de taille que le renderer existant (32 Mio par média).

## Sorties et reprise

- `rendu-01/export/` : MP4, SRT séparé, manifeste, médias copiés et reçu
  d'export reproductible.
- `rendu-01/pipeline_receipt.json` : empreinte du bundle, IDs et révision,
  empreintes source/livrables métier/vidéo/reçu et résultat technique.
- Les sources fournies restent intactes. Les copies temporaires sont
  retirées à la fin normale et sur exception Python.
- `technical_passed` ne valide pas l'art, la voix, la lisibilité,
  l'alignement paroles/sous-titres ou la diffusion. Validation humaine finale
  toujours requise. Les sous-titres ne sont pas incrustés.
- Code de sortie 0 : export et contrôle technique réussis ; 2 : refus,
  interruption gérée ou contrôle technique négatif.
- Le rapport console contient uniquement statuts et codes fixes,
  jamais narrations, prompts ou chemins privés.
- Après échec de rendu, le reçu indique `failed_or_interrupted`.
  Après rejet technique, l'export est conservé pour examen humain et
  le reçu indique `technical_rejected`. Aucun rejeu automatique.
- Après arrêt brutal, un reçu resté `rendering` signifie état incertain,
  pas succès. Inspecter le dossier ; ne pas rejouer à l'aveugle.
- Relancer sur la même destination est refusé. Pour une nouvelle tentative
  décidée manuellement, diagnostiquer, corriger et choisir un nouveau dossier.
  Ne pas supprimer les médias ou traces pour débloquer le pipeline.

## Vérifications exécutées

Python 3.12, environnement de développement isolé :
15 nouveaux tests du pipeline, plus 18 tests du renderer, du critique et
des sous-titres. **33 tests réussis, zéro skip.**
Encodage réel d'un diaporama synthétique de cinq scènes/75 s, 720×1280,
24 i/s et WAV silencieux. Source conservée octet pour octet et provenance
retrouvée dans le manifeste final. Refus de préproduction périmée/incomplète,
score refusé malgré un faux flag passed, chemins sortants/liens,
destination existante et clés JSON dupliquées. Échec simulé sans retry et
export rejeté conservé couverts ; aucune preuve artistique ou GPU.

```bash
PYTHONPATH=tests python -m unittest \
  test_episode_pipeline test_render_critic test_render_episode \
  test_subtitle_quality -v
```

Dépend de #198 et #202 ; PR ciblant #202 pour isoler cet incrément.
Régression complète Python 3.12/3.14, revue, CI et recette PC non réalisées.
Aucune fusion, livraison, migration ni modification des secrets/services.
Suite : raccordement authentifié au Studio avec audit/persistance et
concurrence, génération réelle images/voix, puis recette audiovisuelle sur PC.

## Correction de revue — 18 octobre 2026

Un identifiant de run JSON non textuel (liste, objet ou nombre) provoquait
une exception AttributeError dans UUID et une trace console au lieu du refus
contrôlé. Le type est désormais validé avant conversion, avec le code fixe
`production_run_id_invalid`, sans création de destination ni appel FFmpeg.
Deux tests de non-régression (fonction et CLI) ont échoué avant correction,
puis réussi ; les 35 tests ciblés pipeline/critique/rendu/SRT passent sans skip
en Python 3.12 isolé, avec rendu synthétique FFmpeg/ffprobe réel.
La CI complète, PostgreSQL, Qwen et la recette PC restent non validés ;
aucune fusion ou livraison n'est autorisée par ces seuls résultats ciblés.

## Incrément voix française locale — 18 octobre 2026

La génération vocale manquante est désormais raccordable sur cette branche Lot 3.
`production/voice_timeline.py` produit un WAV PCM mono 24 kHz de 75 secondes :
une synthèse locale par scène, complétée par du silence pour chaque créneau.
Une narration trop longue est rejetée plutôt que coupée.

Prérequis à vérifier sur le PC : exécutable Piper, modèle français .onnx
et sa configuration, FFmpeg. Aucun composant ni modèle n'est installé.

Préparer un bundle approuvé, dont media.voice vaut voice.wav, et ses PNG.
Puis, dans un dossier privé (la cible WAV doit être absente) :

```bash
python scripts/synthesize_production_voice.py \
  /chemin/prive/pilote/bundle.json \
  /chemin/prive/pilote/medias \
  --model /chemin/prive/voix-fr.onnx \
  --confirm-human-review

ffprobe -v error -show_entries format=duration -of default=nw=1 \
  /chemin/prive/pilote/medias/voice.wav

python scripts/render_production.py \
  /chemin/prive/pilote/bundle.json \
  /chemin/prive/pilote/medias \
  /chemin/prive/pilote/rendu-01 \
  --confirm-human-review
```

Les scripts ne modifient pas PostgreSQL, MinIO, les médias existants ou la release PC.
Le texte de narration n'est pas envoyé au réseau par ce code Python.

Recette hors PC : 5 tests Python réussis avec FFmpeg réel et
simulateur de l'interface Piper ; 75 secondes et créneaux vérifiés.
À vérifier encore : Piper réel et modèle français sur PC, diction et
niveaux audio, images réelles, chaîne de bout en bout, régression et CI.
Aucune fusion ou livraison PC pendant cet incrément.
