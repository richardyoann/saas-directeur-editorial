# Audit des blocages — 9 octobre 2026

## Corrections locales

- Dépôt alternatif `.project-git` opérationnel, identité et remote configurés.
  Utiliser `bash scripts/git_project.sh COMMAND`. L’historique reste indépendant
  du dépôt distant ; ne pas forcer un push ni une fusion entre historiques.
- Snapshot complet des sources préparé et contrôlé pour commit local, plutôt
  que les seuls fichiers du contournement Git initial. Aucun code publié.
- `.project-git` exclu des empreintes et manifestes de l’orchestrateur : une
  modification de métadonnées Git ne périme plus les preuves de code.
- `.env`, mémoire privée, sauvegardes `*.bak`, capacités natives et téléchargements
  tiers exclus des commits. `AGENTS.md` est préservé sans modification.
- Skill Git demandé ajouté à `external-skills.json` à la révision fournie,
  avec son dossier complet comme source. Référencé, pas installé.
- Diagnostic sans affichage de secrets :

```bash
.venv/bin/python scripts/diagnose_project.py
```

La commande retourne 1 si un contrôle bloque. Les services et le dépôt distant
peuvent rester `unverified` ; cela ne vaut pas validation. Chaque commande est
limitée à 15 secondes. Aucun téléchargement, démarrage ou changement de droits.

## Restrictions encore constatées

| Point | Preuve | Résolution hors session restreinte |
| --- | --- | --- |
| Réseau GitHub | `ls-remote` : nom d’hôte non résolu ; API inaccessible | Vérifier réseau/DNS dans WSL2 ; relancer le diagnostic dans ce terminal |
| Accès distant | Existence, droits et historique non vérifiables | `gh auth status -h github.com`, puis `gh repo view richardyoann/saas-directeur-editorial` |
| Compose | Plugin absent ; exécutable Windows demande l’intégration WSL | Activer la distribution dans Docker Desktop → Settings → Resources → WSL integration, ou installer Compose v2 |
| Socket Docker | `docker info` : permission denied | Vérifier Docker Desktop et l’accès au socket dans WSL2 ; ne pas rendre le socket accessible à tous |
| Activation native | `.agents` et `.codex` en lecture seule | Exécuter les activateurs depuis WSL2 avec les accès normaux |
| Skills tiers | Huit sources prévues, aucun reçu d’installation | Installer depuis WSL2 connecté avec les commandes ci-dessous |
| Appel Qwen actuel | Sonde API réelle : HTTP 502 | Relancer `scripts/check_llm_integration.py` dans le terminal ayant accès au serveur ; préserver la preuve historique DEV-001 |

La connexion CLI enregistrée ne connecte pas automatiquement l’intégration
GitHub de l’application. Aucun jeton n’est copié dans le dépôt. Aucun service,
volume, migration, configuration système ou règle réseau modifié par cet audit.

## Reprise depuis WSL2

```bash
cd /home/yoann_admin/saas-directeur-editorial
gh auth status --hostname github.com
gh repo view richardyoann/saas-directeur-editorial
bash scripts/git_project.sh ls-remote origin
docker compose version
docker info
docker compose ps
.venv/bin/python scripts/install_project_capabilities.py --apply
.venv/bin/python scripts/install_external_skills.py --apply
.venv/bin/python scripts/install_external_skills.py --check
.venv/bin/python scripts/install_external_skills.py --activate
.venv/bin/python scripts/diagnose_project.py
```

L’installateur préserve les destinations existantes ; consulter ses reçus en cas
d’installation partielle. Vérifier la découverte native dans une nouvelle session.
Une erreur d’accès GitHub ne prouve pas l’absence du dépôt. Avant publication,
récupérer et examiner son historique ; ne pas utiliser `push --force`.

## Validation

53 tests automatisés réussis. Parcours CLI isolé : 15 commandes réussies,
19 événements vérifiés. Les tests d’installation restent simulés ; aucun
téléchargement effectif ni merge distant n’est annoncé.
