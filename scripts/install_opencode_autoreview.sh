#!/usr/bin/env bash
# Installe le hook Arvor partage et un worker persistant hors du checkout.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
hook_source="$root/scripts/hooks/post-commit"
worker_source="$root/scripts/opencode_auto_review_commit.sh"
[[ -f "$hook_source" && -f "$worker_source" ]] || {
  echo "Scripts d'autorevue manquants"; exit 2;
}
configured="$(git config --get core.hooksPath || true)"
if [[ -n "$configured" ]]; then
  if [[ "$configured" = /* ]]; then hookdir="$configured"
  else hookdir="$root/$configured"; fi
else
  common="$(git rev-parse --git-common-dir)"
  hookdir="$(cd "$common" && pwd -P)/hooks"
fi
mkdir -p "$hookdir"
target="$hookdir/post-commit"
old_blob="3ca8cb70eb9ce94be579e9f5b211b32f24b4a929"
upgrade_legacy=false
if [[ -e "$target" ]]; then
  if cmp -s "$hook_source" "$target"; then
    echo "Hook Arvor V2 deja present."
  elif [[ "$(git hash-object "$target")" == "$old_blob" ]]; then
    upgrade_legacy=true
  else
    echo "Hook tiers ou modifie detecte : $target"
    echo "Aucune substitution effectuee ; fusionner les hooks manuellement."
    exit 2
  fi
fi
data_home="${XDG_DATA_HOME:-$HOME/.local/share}/arvor-opencode"
mkdir -p "$data_home"
chmod 700 "$data_home"
worker_target="$data_home/opencode_auto_review_commit.sh"
if [[ -f "$worker_target" ]] && ! cmp -s "$worker_source" "$worker_target"; then
  if ! grep -Fq '# Revue du SHA commite' "$worker_target"; then
    echo "Worker tiers detecte ; copie refusee : $worker_target"
    exit 2
  fi
  backup="$(mktemp "$data_home/worker-backup.XXXXXX")"
  cp "$worker_target" "$backup"
  chmod 600 "$backup"
fi
cp "$worker_source" "$worker_target"
chmod 700 "$worker_target"
if [[ "$upgrade_legacy" == true ]]; then
  backup="$(mktemp "$hookdir/post-commit-v1-backup.XXXXXX")"
  cp "$target" "$backup"
  chmod 600 "$backup"
  echo "Sauvegarde ancien hook : $backup"
fi
if [[ ! -e "$target" || "$upgrade_legacy" == true ]]; then
  cp "$hook_source" "$target"
  chmod 700 "$target"
fi
echo "Hook Arvor installe : $target"
echo "Worker independant des branches : $worker_target"
echo "Apres chaque nouveau git commit : rapport dans ~/.local/state/arvor-opencode/reports/"
echo "Aucun push, merge, test CI ou deploiement automatique."
