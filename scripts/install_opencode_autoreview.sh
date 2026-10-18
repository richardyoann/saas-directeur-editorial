#!/usr/bin/env bash
# Active la revue OpenCode automatique apres chaque commit du depot.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
source_file="$root/scripts/hooks/post-commit"
worker="$root/scripts/opencode_auto_review_commit.sh"
[[ -f "$source_file" && -f "$worker" ]] || { echo "Scripts OpenCode manquants dans ce checkout"; exit 2; }
configured="$(git config --get core.hooksPath || true)"
if [[ -n "$configured" ]]; then
  if [[ "$configured" = /* ]]; then
    hookdir="$configured"
  else
    hookdir="$root/$configured"
  fi
else
  common="$(git rev-parse --git-common-dir)"
  hookdir="$(cd "$common" && pwd -P)/hooks"
fi
mkdir -p "$hookdir"
target="$hookdir/post-commit"
if [[ -e "$target" ]]; then
  if cmp -s "$source_file" "$target"; then
    echo "Hook Arvor deja installe: $target"
    exit 0
  fi
  echo "Hook post-commit preexistant conserve : $target"
  echo "Pour eviter d'ecraser un hook tiers, integrer manuellement scripts/hooks/post-commit."
  exit 2
fi
cp "$source_file" "$target"
chmod 700 "$target"
echo "Hook post-commit installe: $target"
echo "Au prochain git commit, OpenCode analysera le SHA en arriere-plan si le modele est accessible."
echo "Statuts: ~/.local/state/arvor-opencode/reports/*.status"
echo "Le hook est commun aux worktrees qui partagent ce depot Git."
