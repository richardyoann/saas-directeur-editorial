#!/usr/bin/env bash
# Revue du SHA commite dans un worktree ephemere, sans publication ni livraison.
set -euo pipefail
export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$HOME/bin:$PATH"
root="${1:?Repository required}"
sha="${2:?Commit SHA required}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -d "$root" ]] || exit 2
state="${XDG_STATE_HOME:-$HOME/.local/state}/arvor-opencode"
mkdir -p "$state/reports"
chmod 700 "$state" "$state/reports"
umask 077
report="$state/reports/$sha.md"
status="$state/reports/$sha.status"
log="$state/reports/$sha.log"
printf 'pending %s\n' "$sha" > "$status"
command -v flock >/dev/null || { echo "flock absent" > "$status"; exit 2; }
command -v timeout >/dev/null || { echo "timeout absent" > "$status"; exit 2; }
command -v opencode >/dev/null || { echo "opencode absent du PATH" > "$status"; exit 2; }
exec 9>"$state/review.lock"
if ! flock -w 1200 9; then
  printf 'error lock_timeout %s\n' "$sha" > "$status"
  exit 1
fi
if [[ -s "$report" ]]; then
  printf 'ok already_reviewed %s\n' "$sha" > "$status"
  exit 0
fi
model="arvorlocal/coder"
model_config="$HOME/.config/arvor-opencode-review-model"
if [[ -f "$model_config" ]]; then
  model="$(head -n 1 "$model_config")"
fi
if [[ ! "$model" =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]]; then
  echo "Invalid model identifier" > "$status"
  exit 2
fi
if [[ "$model" == "arvorlocal/coder" ]]; then
  windows_ip="$(ip -4 route show default 2>/dev/null | awk '{print $3; exit}')"
  if [[ -z "$windows_ip" ]] || ! curl -fsS --noproxy '*' --connect-timeout 2 --max-time 4 \
      "http://$windows_ip:8083/v1/models" >/dev/null 2>&1; then
    printf 'skipped local_model_offline %s\n' "$sha" > "$status"
    exit 0
  fi
fi
snapshot="$(mktemp -d "$state/snapshot-XXXXXX")"
registered=0
cleanup() {
  if [[ "$registered" == 1 ]]; then
    git -C "$root" worktree remove --force "$snapshot/repository" >/dev/null 2>&1 || true
  fi
  rmdir "$snapshot" 2>/dev/null || true
}
trap cleanup EXIT
if ! GIT_LFS_SKIP_SMUDGE=1 git -C "$root" worktree add --detach "$snapshot/repository" "$sha" >/dev/null 2>>"$log"; then
  printf 'error snapshot_failed %s\n' "$sha" > "$status"
  exit 1
fi
registered=1
unset GITHUB_TOKEN GH_TOKEN PO_DATABASE_URL EDITORIAL_API_TOKEN EDITORIAL_WEB_PASSWORD \
  EDITORIAL_TENANT_ID EDITORIAL_ACTOR_ID MINIO_ROOT_PASSWORD MINIO_ROOT_USER || true
cd "$snapshot/repository"
printf 'running %s %s\n' "$sha" "$model" > "$status"
prompt="Analyse le commit Git exact $sha en lecture seule. Lis AGENTS.md et docs/OPENCODE_OPENWORK_ARCHITECTURE.md. Delegue aux sous-agents architecture, securite et UI. Identifie anomalies, risques, regressions et tests manquants. Ne modifie rien, ne publie rien et ne lance pas de deploiement. Ne reproduis aucune donnee privee. Ce rapport ne remplace pas les tests QA."
if timeout --signal=TERM --kill-after=10s 900s opencode run \
    --model "$model" --agent arvor-orchestrator "$prompt" > "$report.tmp" 2>"$log"; then
  mv "$report.tmp" "$report"
  printf 'ok %s %s\n' "$sha" "$model" > "$status"
else
  result=$?
  mv "$report.tmp" "$report.failed" 2>/dev/null || true
  printf 'error opencode_exit_%s %s\n' "$result" "$sha" > "$status"
  exit "$result"
fi
