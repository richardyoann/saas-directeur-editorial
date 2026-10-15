# MEDIA-002 — commande de diagnostic, 15 octobre 2026

Baseline inspectée : `78cfc30d88da79f7b887977dfaf7f26bbe428048`.

## Défaut reproduit et correction

La commande documentée `python scripts/diagnose_image_runtime.py` échouait
avec `ModuleNotFoundError: No module named 'editorial'`, même avec HTTPX
installé. L'exécution directe place `scripts/` dans le chemin d'import.
Le script ajoute désormais la racine du dépôt, calculée depuis son fichier,
avant de charger le contrat du fournisseur. Aucune modification du runtime,
du pilote, de la base ni téléchargement de modèle.

Le contrat de MEDIA-001 est aligné sur MEDIA-002 et le code existant :
`output_format: png` dans la requête et `data[0].b64_json` dans la réponse.

## Vérification

`python -m unittest discover -s tests -p test_image_preflight_cli.py -v`
exécute réellement le script dans un sous-processus depuis un autre dossier,
sans le projet dans PYTHONPATH. Une URL publique est refusée avant tout
appel HTTP : code 2, JSON valide, aucun traceback, `gpu_verified=false`
et `generation_verified=false`. Résultat local : 1 test réussi, aucun skip.
La régression complète et la CI doivent être vérifiées sur le SHA de la PR.

## Recette PC restant obligatoire pour clore le lot 2

1. Identifier la RX 580 dans Vulkan et relever la version du pilote.
2. Vérifier le binaire sd-server, son modèle et la connexion privée depuis WSL.
3. Après autorisation du SHA exact pour activation PC, utiliser une histoire
   de trois scènes avec personnage récurrent et scénario approuvé humainement.
4. Générer chaque image une seule fois depuis Studio, sans rejeu ambigu.
5. Vérifier les trois PNG privés, leurs liens scène/version, audit et historique.
6. Relever les durées et la VRAM ; qualifier visuellement la cohérence humaine.

Aucun de ces six points n'est attesté par ce correctif ou un serveur simulé.
Le lot 2 reste ouvert jusqu'aux preuves PC et à la revue éditoriale.
Retour arrière : réversion du correctif de code ; aucun média ni donnée à effacer.
