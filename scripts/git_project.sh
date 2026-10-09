#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Prefer the original repository when its metadata becomes available.
if git -C "$project_root" rev-parse --git-dir >/dev/null 2>&1; then
    exec git -C "$project_root" "$@"
fi

# The environment protects .git; keep local metadata in a writable directory.
if [[ ! -f "$project_root/.project-git/HEAD" ]]; then
    printf '%s\n' 'Dépôt alternatif absent ; consulter docs/REPOSITORY_SETUP.md.' >&2
    exit 1
fi
exec git --git-dir="$project_root/.project-git" --work-tree="$project_root" "$@"
