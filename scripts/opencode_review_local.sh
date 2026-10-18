#!/usr/bin/env bash
# Analyse indépendante de la PR par OpenCode (aucune MEP, aucun push).
set -euo pipefail
export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$HOME/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v opencode >/dev/null || { echo "OpenCode introuvable dans PATH ; exécuter source ~/.bashrc et vérifier ~/.opencode/bin/opencode"; exit 1; }
sha="$(git rev-parse HEAD)"
output="${ARVOR_REPORT_DIR:-$HOME/.local/state/arvor-reviews}"
mkdir -p "$output"
chmod 700 "$output"
report="$output/review-$sha.md"
umask 077
opencode run --agent arvor-orchestrator "Examine le code au SHA $sha en lecture seule. Respecte AGENTS.md. Délègue revues architecture/sécurité/UI, indique risques et tests manquants, aucune modification ou déploiement. Ne reproduis ni secrets ni données métier. Un avis LLM ne vaut pas QA réussie." > "$report"
printf 'Rapport créé : %s\n' "$report"
printf 'Pour les tests réels, lancer scripts/local_quality_gate.py indépendamment.\n'
