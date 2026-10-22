#!/usr/bin/env bash
# Run from a reviewed, trusted Arvor controller checkout (NOT the target PR).
set -uo pipefail
if [[ $# -ne 4 ]]; then
  echo 'Usage: run_and_report.sh <target-clean-checkout> <sha40> <base-sha40> <pr-number>' >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
state="${ARVOR_CI_STATE_DIR:-$HOME/.local/state/arvor-ci}"
umask 077
mkdir -p "$state"
chmod 700 "$state"
nonce="$(date -u +%Y%m%dT%H%M%SZ)-$$"
raw="$state/$nonce-raw.json"
proof="$state/$nonce-signed.json"
python3 "$root/scripts/arvor_ci_run.py" --target "$1" --sha "$2" --base "$3" --output "$raw"
quality_rc=$?
if [[ ! -s "$raw" ]]; then
  echo 'No verifiable CI evidence. Send a manual failure alert; nothing published.' >&2
  exit 2
fi
python3 "$root/scripts/arvor_ci_publish.py" seal --report "$raw" --output "$proof" --sha "$2" || exit 2
python3 "$root/scripts/arvor_ci_publish.py" publish --proof "$proof" --sha "$2" --pr "$4" || exit 2
exit "$quality_rc"
