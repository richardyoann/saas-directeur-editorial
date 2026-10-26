# Lot 3 — contrôle des sous-titres du rendu final

## Incrément implémenté

Suite de la préproduction de la PR #198, sur une branche distincte.
Le critique MP4 appelle maintenant un validateur SRT avant de qualifier
l'export. Un fichier non vide ne suffit plus.

Contrôles : blocs numérotés à partir de 1, horodatages SRT valides,
durée strictement positive, fin au plus à 75 000 ms, ordre chronologique,
absence de chevauchement et présence de texte. UTF-8 avec BOM et CRLF
Windows acceptés. Les pauses entre sous-titres restent autorisées.
Les erreurs utilisent des codes fixes ; aucun texte ni chemin privé
n'est ajouté au rapport.

## Validation exécutée

Python 3.12 dans un environnement isolé, sans accès au PC :
- 10 nouveaux tests réussis, zéro skip.
- 4 tests existants du critique réussis, zéro skip.
- 4 tests existants du rendu réussis, zéro skip.
- Vrai encodage FFmpeg et vraie inspection ffprobe d'un MP4 synthétique
  75 s, 720×1280, 24 i/s avec piste audio silencieuse.
- Le même export est refusé après remplacement du SRT par un sous-titre
  finissant à 76 s.
- Tests des chevauchements, ordre/numérotation, intervalles inversés/nuls,
  caractères UTF-8 invalides et formats de temps erronés.

Commandes :

```bash
python -m unittest discover -s tests -p test_subtitle_quality.py -v
python -m unittest discover -s tests -p test_render_critic.py -v
python -m unittest discover -s tests -p test_render_episode.py -v
```

## Portée et suite

Ce contrôle ne prouve pas l'alignement avec les paroles, l'exhaustivité de
la transcription, la lisibilité ni une bonne qualité audiovisuelle.
L'acceptation humaine reste obligatoire. Les sous-titres restent un fichier
séparé, sans incrustation ni modification du MP4.

Restent à réaliser : orchestration effective image/voix/montage depuis
les livrables de préproduction, critique multimodale, recette Qwen et RX 580,
et première légende réelle. Cet incrément ne clôture pas le lot 3.

Dépendance : PR #198 non fusionnée. PR de suite ciblant sa branche pour
garder un diff limité. Après évolution de cette dépendance, revalider
la compatibilité et la CI complète avant fusion. Aucune migration, donnée
métier, variable de déploiement, secret ou service PC modifié.
Pas de livraison PC.
