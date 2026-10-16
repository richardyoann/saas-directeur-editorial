# MEDIA-003 — premier export vidéo reproductible

16 octobre 2026. Base inspectée : `25e5d4aff298fc30c85012c75de4fc0d116821c5`.

## Périmètre réellement développé

CLI hors ligne : images PNG locales → MP4 H.264 vertical 720×1280, 24 fps,
avec voix WAV facultative, audio AAC et sous-titres SRT séparés. Aucune génération
image/voix, aucune publication et aucun appel réseau. Le rendu est un diaporama
à coupes franches ; les sous-titres ne sont pas incrustés dans la vidéo.
Le script ne remplace pas l'authentification ni les validations du Studio.
Le champ `approved` est une déclaration explicite de l'opérateur hors ligne,
pas une preuve de validation retrouvée en base.

## Prérequis et exécution

Python 3.12 et FFmpeg/ffprobe avec encodeur libx264. Pas de dépendance Python
supplémentaire. FFmpeg est installé dans la CI de régression ; son installation
sur le PC reste distincte et n'est pas effectuée par ce changement. Avant une
future livraison, vérifier `ffmpeg -version` et `ffprobe -version` dans WSL
Ubuntu 26.04 : le test réel échoue au gate de livraison si le prérequis manque
(un skip n'est pas une réussite). Aucun service ni modèle n'est modifié.

Après approbation du scénario, placer ses images et une voix enregistrée
localement dans un dossier privé hors release. Créer `production.json` :

```json
{
  "schema_version": 1,
  "approved": true,
  "voice": "voix.wav",
  "scenes": [
    {"image": "scene-1.png", "duration_seconds": 15, "narration": "Texte validé de la première scène."},
    {"image": "scene-2.png", "duration_seconds": 15, "narration": "Texte validé de la deuxième scène."}
  ]
}
```

Les durées sont celles du scénario, de 1 à 180 secondes par scène, six scènes
et 180 secondes au maximum par épisode. La voix doit couvrir la durée totale
à 0,25 seconde près. Omettre `voice` produit explicitement une vidéo muette.
Les fichiers doivent être dans ce dossier ou ses sous-dossiers : chemins
absolus, sorties du dossier et liens symboliques refusés. Ne pas utiliser de
dossier partagé avec un autre utilisateur pendant le rendu.

```bash
python scripts/render_episode.py /dossier/prive/pilote/production.json /dossier/prive/pilote-export-01
```

La destination doit être nouvelle et son parent déjà présent. Aucun fichier
existant n'est écrasé. Un échec nettoie uniquement la nouvelle destination.
La sortie comprend `episode.mp4`, `narration.srt`, images, voix éventuelle,
`production.json` adapté et `receipt.json` (empreintes, durée, FFmpeg).
Les textes/prompts ajoutés manuellement au manifeste sont conservés : ces
fichiers restent privés, à exclure des journaux, du dépôt et de Slack.

Reproduction : utiliser le `production.json` du dossier exporté vers une
autre destination. Les sources sont conservées ; l'identité binaire du MP4
entre versions de FFmpeg ou machines n'est pas garantie.

## Recette 80/20 et blocages restants

| Priorité | État vérifié | Preuve encore nécessaire |
| --- | --- | --- |
| Installation PC | Dernier run delivery `38771922089` skipped sur la base inspectée | SHA current, reçu, services, réouverture après redémarrage |
| Parcours texte | Routes et Studio présents, régression GitHub de la base réussie | Histoire réelle créée, modifiée et retrouvée sur PC |
| LLM | Contrats et gestion d'erreurs déjà développés | Recette réelle de cette installation |
| Scènes/images | Intégration locale SD.cpp et reçus présents | PNG réellement générés, cohérence validée humainement |
| Export | CLI développée et testée avec vrai FFmpeg, PNG synthétique et WAV silencieux | Pilote artistique 30–60 s avec voix et images réelles |
| Reproductibilité | Sources, manifeste, SRT et empreintes exportés | Deuxième épisode réel avec le même processus |
| Sauvegardes | Non exercées pendant ce travail | Restauration isolée et preuve de récupération |

Tests locaux : `python -m unittest discover -s tests -p test_render_episode.py -v`.
Le test encode un vrai MP4, inspecte ses pistes/dimensions et reproduit l'export
depuis les sources copiées. Il ne prouve ni rendu GPU ni voix de synthèse.

Avant toute activation PC : revue et CI sur SHA final, validation explicite
du SHA suivant AGENTS.md. Pas de migration SQL. Retour arrière : ne plus utiliser
la CLI ou revenir au code précédent ; garder les dossiers de production.
