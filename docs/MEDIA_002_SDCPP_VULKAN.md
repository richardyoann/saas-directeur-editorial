# MEDIA-002 — Raccordement stable-diffusion.cpp Vulkan (préparation, sans installation)

## But et statut

Provenance, durée et contrôle sans génération :
[MEDIA_002_IMAGE_RECEIPTS.md](MEDIA_002_IMAGE_RECEIPTS.md).

Cette évolution prépare un serveur d'images **local et privé** pour le PC
Windows 11, RX 580 8 Go, et l'application Arvor Studio dans Ubuntu WSL.
Elle valide le **contrat réel HTTP** d'un serveur compatible
`stable-diffusion.cpp`, sans en déduire que le GPU a produit une image.

- Le **texte** reste généré par Qwen et persisté en PostgreSQL.
- Les profils de personnages et les prompts de scène existent déjà (MEDIA-001).
- Les **pixels** proviendront d'un **second programme**, `sd-server`, via
  `POST /v1/images/generations`. Le SDK image ne remplace pas Qwen.
- Le code utilise `{"prompt":"…","n":1,"size":"512x512","output_format":"png"}`.
  La réponse doit contenir exactement `data[0].b64_json` avec un PNG.
  Le champ `response_format` précédent a été retiré, car il n'est pas
  documenté pour ce serveur.
- Les images ne sont demandées que sur scénario approuvé, une par scène,
  via Studio avec authentification et contrôle anti-rejeu. Aucune
  publication automatique.

Source officielle :
[SD.cpp APIs](https://github.com/leejet/stable-diffusion.cpp/blob/master/examples/server/api.md),
[construction Vulkan](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/build.md),
[usage sd-server](https://github.com/leejet/stable-diffusion.cpp/blob/master/examples/server/README.md).

## 1. Diagnostic sans modification sur Windows

Ouvrir PowerShell, depuis un clone local de ce dépôt contenant le script :

```powershell
powershell -NoProfile -File .\scripts\diagnose_vulkan_windows.ps1
```

Le script affiche les GPU et versions de pilotes, tente de lire
`vulkaninfo --summary` si l'outil est présent, puis vérifie si un
processus répond localement sur le port TCP 8082. Il ne lance ni
installateur, ni mise à jour, ni outil de génération.

Critères pour poursuivre :

1. `vulkaninfo` identifie réellement **Radeon RX 580** (pas seulement un
   adaptateur logiciel `llvmpipe`). Si absent, diagnostiquer la disponibilité
   de Vulkan avant d'installer quoi que ce soit.
2. Les outils CMake, Visual Studio C++ Build Tools et Vulkan SDK/compilateur
   sont disponibles **si** compilation locale choisie. Leur présence n'est
   pas présumée.
3. Les poids du modèle sont issus d'une source de confiance et la licence
   autorise l'usage envisagé. Ne pas télécharger automatiquement un modèle
   arbitraire ni copier un chemin réel dans Git.

Pour un premier essai, privilégier une version de
Stable Diffusion 1.5 compatible sd.cpp, **512×512**, avec un seul job à la fois.
Ce choix est une hypothèse technique pour limiter la VRAM : compatibilité,
qualité et latence sur RX 580 **non garanties**.

## 2. Exemple de construction native Windows (facultatif, NON exécuté)

Après vérification du SDK Vulkan et des outils C++, à exécuter dans une
console développeur Visual Studio **sur le PC et uniquement après accord
explicite pour cette installation** :

```powershell
git clone --recursive https://github.com/leejet/stable-diffusion.cpp
Set-Location stable-diffusion.cpp
# Sélectionner et vérifier un commit amont précis AVANT construction
git rev-parse HEAD
cmake -S . -B build -DSD_VULKAN=ON -DSD_SERVER_BUILD_FRONTEND=OFF
cmake --build build --config Release
```

Confirmer le binaire exact créé (`build/bin` ou `build/bin/Release` selon
générateur), puis démarrer en privé (chemins d'exemple à adapter) :

```powershell
.\build\bin\Release\sd-server.exe -m "D:\modeles\sd15.safetensors" --listen-ip 127.0.0.1 --listen-port 8082
```

La syntaxe `-m` et les options doivent être vérifiées avec
`sd-server.exe -h` sur **la version compilée** ; le format du modèle chargé
peut exiger des fichiers VAE/encodeurs distincts. Aucun de ces chemins ne
constitue une preuve que le modèle ou l'exécutable existe.

**Réseau WSL/Windows :** le mode WSL mirrored peut permettre `localhost`.
En mode NAT, la loopback Windows peut ne pas être joignable depuis WSL.
**Ne pas élargir à `0.0.0.0` ni désactiver le pare-feu automatiquement.**
Résoudre explicitement une liaison privée authentifiée/filtrée avant de
configurer une adresse Windows hôte. Une IP WSL passée n'est pas pérenne.

## 3. Préflight SD.cpp (aucune image fabriquée)

Dans Ubuntu WSL, depuis une release qui intègre MEDIA-002, avec l'URL
privée réellement joignable :

```bash
cd ~/editorial-runtime/current
IMAGE_BASE_URL=http://127.0.0.1:8082 \
  .venv/bin/python scripts/diagnose_image_runtime.py
```

Exemple **fictif** :

```json
{
  "ready": true,
  "reason": "image_api_models_listed",
  "model_count": 1,
  "gpu_verified": false,
  "generation_verified": false
}
```

Ce diagnostic n'envoie aucun prompt. Il vérifie seulement le contrat
`GET /v1/models` et le format des identifiants de modèle. Une liste
de modèles **ne prouve jamais** que Vulkan ou le GPU fonctionne ; même un
moteur simulé peut renvoyer une telle réponse. Ne pas afficher l'URL de
base dans les logs automatiques (elle peut identifier la machine).

Codes de sortie : `0` si API compatible accessible, `2` sinon.

## 4. Configuration métier après validation de MEP

Paramètres préexistants du SaaS (à conserver dans le secret/runtime, jamais
dans les commits ou captures) :

```dotenv
IMAGE_BASE_URL=http://127.0.0.1:8082
EDITORIAL_MEDIA_ROOT=/chemin/prive/media
```

Ne pas écraser le fichier de configuration actif ni modifier les permissions
des autres services. Le script ne crée aucun service ni dossier.

**Test métier réel nécessaire après configuration :**
produire une histoire de 3 scènes et au moins un personnage récurrent avec
Qwen, vérifier que le scénario est approuvé, générer une image par scène à
512×512, contrôler leur ouverture privée depuis Studio et leur présence
historisée en base/audit, et consigner durée réelle et consommation VRAM.
Ne pas rejouer automatiquement une génération dont l'état est ambigu.

## 5. Tests livrés dans ce lot

- `tests/test_visuals.py` vérifie que les requêtes d'images utilisent
  les paramètres **documentés par sd-server**.
- `tests/test_sd_cpp_bridge.py` démarre un microserveur local de
  test sur un port éphémère et vérifie `GET /v1/models`,
  trois `POST /v1/images/generations`, les images PNG et les
  repères visuels du personnage dans chacun des trois prompts.
- Les suites PostgreSQL/Studio antérieures couvrent le stockage,
  l'authentification et les statuts.

**Attention** : ce microserveur retourne une image miniature préfabriquée,
pas une vraie synthèse. Il ne représente pas un test GPU ni une
production artistique réussie.

## 6. Sécurité, reprise et limites

- Aucun téléchargement ou exécution de binaire tiers dans CI.
- Aucune variable GitHub d'activation PC modifiée.
- Aucune migration DB, aucune création/suppression d'images utilisateur.
- URLs publiques et redirections d'image interdites ; contenu PNG borné.
- Pas de retry automatique sur timeout : diagnostiquer l'asset
  `generating` ou `failed` avant réconciliation manuelle.
- Retour arrière : réverter ce correctif ou revenir à la release
  privée précédente ; aucun modèle ou nouveau stockage à nettoyer.
- L'adaptation SD.cpp Vulkan n'est pas une preuve de qualité des
  personnages entre les scènes. Pour renforcer la cohérence,
  des références visuelles ou LoRA seront à évaluer ensuite.

**Condition de livraison :** tests GitHub et revue au SHA exact, puis
validation explicite du SHA final pour installer sur le PC.
