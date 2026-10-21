# Lot 2 — stabilisation Qwen, diagnostic sans données métier

Baseline : `main` au SHA `d08fe0afe62f0ea209da239aeade0bd5f042d30d`. Branche préparatoire du 17 octobre 2026. Pas de déploiement PC.

## Analyse vérifiée

- FastAPI et le worker utilisent `generate_text` : deux appels maximum dans `editorial.service`, sans reprise automatique après une erreur Qwen.
- Pydantic valide strictement les structures `Analysis` et `Storyboard`, les scènes et la durée totale. Les sorties non arrêtées par `finish_reason=stop` échouent ; pas de réparation automatique d'un JSON tronqué.
- `output_schema()` transmettait le JSON Schema Pydantic directement au serveur, avec références `$defs`/`$ref` pour `Scene` et `CharacterProfile`. Certains builds de llama.cpp sont connus pour ignorer ou échouer sur les grammaires complexes ; ceci est un risque réel de compatibilité, **pas une preuve de panne constatée sur ce PC**.
- La version exacte de llama.cpp, le GGUF chargé, la capacité du contexte et le débit GPU de la RX 580 ne sont pas observables via GitHub. Aucun verdict « Qwen stabilisé en production » sans recette PC.

## Correctifs préparés

1. Expansion déterministe, sans mutation, des seules références locales du schéma Pydantic avant l'envoi à llama.cpp ; erreurs fermées sur références manquantes, externes, récursives ou ambiguës.
2. Conservation de la **validation métier stricte Python**, du contrat de génération JSON de llama.cpp, du nombre de scènes, des durées et de l'interdiction de retry implicite. Aucun fallback en texte libre.
3. Script `scripts/verify_qwen_structured.py` : vérifie uniquement `GET /health` par défaut, en autorisant seulement un endpoint LLM privé. `--generate` réalise volontairement **deux appels Qwen au maximum**, avec brief fictif non sensible, sans PostgreSQL ni MinIO, et n'affiche que des catégories de succès/échec ; pas de prompt, réponse, URL ni token dans sa sortie. Échec analysis = aucun second appel.
4. Tests unitaires de schéma, refus des références invalides, URLs privées et résultat tronqué, sans réseau ni données de production.

## Vérifier sur PC, après simple git fetch, sans modifier la release actuelle

Utiliser une copie de travail séparée du code de la PR avec l'environnement Python existant, en chargeant uniquement le `.env` privé hors Git si nécessaire :

```bash
cd ~/saas-directeur-editorial-github
git fetch origin
git worktree add --detach ~/arvor-qwen-check origin/fix/qwen-schema-stability-20261017
cd ~/arvor-qwen-check
# Installer aucune dépendance nouvelle ; utiliser un Python déjà doté des dépendances du projet.
~/editorial-runtime/current/.venv/bin/python -m unittest tests.test_qwen_hardening tests.test_verify_qwen_structured -v

# Diagnostic lecture-seule : santé du moteur (aucune génération)
~/editorial-runtime/current/.venv/bin/python scripts/verify_qwen_structured.py

# Recette volontaire : deux inférences fictives, sans écriture en base
~/editorial-runtime/current/.venv/bin/python scripts/verify_qwen_structured.py --generate
```

**Important :** `git worktree` ne copie pas le fichier `.env` non versionné. Le script récupère `LLM_BASE_URL` des variables du processus ou d'un `.env` situé dans **cette copie de travail**, jamais d'un emplacement utilisateur supposé. Préférer exporter cette seule variable dans la session depuis la configuration privée existante sans l'imprimer. Ne pas copier le fichier de secrets dans le dépôt ou une issue. Ne pas installer cette branche comme service PC sans validation du SHA exact.

Un test `health=ok` prouve seulement que le port répond ; seul `--generate` teste l'analyse et le storyboard. Les tests unitaires mockés prouvent le contrat, pas les performances ni le modèle réel.

## Statut Lot 2

- PR #87 **fusionnée** le 15 octobre : empreintes, provenance, audit images, contrôle de cohérence des repères personnages et erreurs sans rejeu. Vérifications d'image **simulées en CI**.
- À faire pour clôturer : vrai rendu de **trois images** via stable-diffusion.cpp sur RX 580, vérification de la cohérence artistique par un humain, mesure de durée et VRAM, validation du dépôt de médias et de l'intégrité sur le PC.
- Mode asynchrone toujours opt-in, non prouvé actif sur PC. Aucun changement de secrets, schéma PostgreSQL, lancement de worker ou modèles.

## Références fournisseur

- https://github.com/ggml-org/llama.cpp/issues/21228 : limitations de grammaires imbriquées.
- https://github.com/ggml-org/llama.cpp/blob/master/examples/json_schema_pydantic_example.py : format `json_object` + `schema`.
- https://github.com/leejet/stable-diffusion.cpp/blob/master/examples/server/api.md : contrat d'images.

## Validation / limites

Tant que le quota GitHub Actions est épuisé, aucune CI nouvelle n'a pu valider cette PR. Tests locaux sur environnement jetable et recette PC restent à réaliser. Aucune affirmation de succès de génération réelle ni d'installation.
