# Création du dépôt GitHub

## Cible autorisée

- Propriétaire : `richardyoann`.
- Nom : `saas-directeur-editorial`.
- URL cible : `https://github.com/richardyoann/saas-directeur-editorial.git`.
- Visibilité préparée : privée par défaut, aucune visibilité explicitement demandée.
- Description proposée : `SaaS Directeur éditorial IA`.

## État vérifié

### Contournement local du 9 octobre 2026

Le dossier `.git` protégé reste inchangé. Un dépôt local indépendant utilise
`.project-git/`, exclu du versionnement. Il ne récupère aucun historique GitHub.
Identité configurée localement : `Yoann RICHARD <yoannichard@gmail.com>`.
Le remote `origin` vise l’URL autorisée ci-dessus ; son accès n’est pas confirmé.

Dans cet environnement, utiliser :

```bash
bash scripts/git_project.sh status
bash scripts/git_project.sh log --oneline
bash scripts/git_project.sh diff
```

Le script accepte les commandes Git habituelles, dont `add`, `commit`, `fetch`
et `merge`. Si le dépôt original devient accessible, il lui donne la priorité.
Ne pas fusionner ou pousser cet historique indépendant avant d’avoir récupéré
et examiné celui du dépôt distant. `.env`, la mémoire privée, les installations
natives et les métadonnées alternatives sont exclus par `.gitignore`.
La connexion GitHub nécessite encore l’installation et l’autorisation de
l’intégration, ou une authentification Git dans un terminal WSL2 normal.

### État initial

### Authentification persistante — vérification ultérieure

GitHub CLI est désormais installé dans WSL2. Le compte actif `richardyoann`
est enregistré dans la configuration locale de `gh` ; aucun jeton n’est copié
dans le projet. Git utilise `gh auth git-credential`, configuré globalement
et explicitement dans le dépôt alternatif `.project-git`.
Ce réglage est conservé entre les processus et les sessions sur cette machine.

La validité de la connexion distante reste non vérifiée : la résolution DNS
de `github.com` échoue dans l’environnement restreint. Le résultat négatif
de `gh auth status` ici ne suffit donc pas à conclure que le jeton est invalide.
Depuis un terminal WSL2 disposant du réseau, vérifier :

```bash
gh auth status --hostname github.com
bash scripts/git_project.sh ls-remote origin
```

L’intégration GitHub de l’application demeure séparée de cette connexion CLI.

### État historique avant installation de GitHub CLI

La création n’a pas été exécutée. La consultation publique ne permet pas de
confirmer l’existence du dépôt. GitHub CLI (`gh`) est absent de l’environnement
Codex ; `.git` local est inexploitable et en lecture seule.
L’intégration GitHub est disponible dans le catalogue, mais non installée/non
connectée lors de la vérification. Son accès doit être confirmé avant utilisation.

## Reprise

Installer et connecter l’intégration GitHub au compte disposant des droits sur
`richardyoann`. Vérifier d’abord si le dépôt existe et si la connexion permet sa
création. Une connexion confirmée ne prouve pas que la création est supportée.

Alternative dans un terminal authentifié où GitHub CLI est déjà disponible :

```bash
gh repo view richardyoann/saas-directeur-editorial
gh repo create richardyoann/saas-directeur-editorial \
  --private --description "SaaS Directeur éditorial IA"
```

Exécuter la création seulement si l’absence du dépôt est confirmée ; une erreur
d’authentification ne prouve pas son absence. Aucun téléchargement/installateur
système, initialisation Git, remplacement de remote ou push automatique effectué.
Avant de relier et publier le code, examiner le Git réellement accessible hors
Codex et préserver branches, remotes et modifications existantes. Exclure `.env`
et secrets de tout commit. La mission de suivi est `OPS-REPOSITORY`.
