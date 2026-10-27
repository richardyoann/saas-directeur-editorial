#!/usr/bin/env bash
# Install, enable and verify the private Arvor MLflow user service.
# No secret is read or printed here: the unit consumes 0600 EnvironmentFile.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SOURCE="$ROOT/deploy/systemd/arvor-mlflow.service"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_TARGET="$UNIT_DIR/arvor-mlflow.service"
VENV_PYTHON="$HOME/.local/state/arvor-mlflow/venv/bin/python"
HEALTH="$ROOT/scripts/mlflow_healthcheck.py"
CLIENT_ENV="$HOME/.config/arvor-mlflow/client.env"
SERVER_ENV="$HOME/.config/arvor-mlflow/mlflow.env"

for file in "$UNIT_SOURCE" "$VENV_PYTHON" "$HEALTH" "$CLIENT_ENV" "$SERVER_ENV"; do
  if [[ ! -e "$file" ]]; then
    echo "missing prerequisite: $file" >&2
    exit 2
  fi
done
if [[ "$(stat -c %a "$SERVER_ENV")" != "600" || "$(stat -c %a "$CLIENT_ENV")" != "600" ]]; then
  echo "configuration files must be mode 600" >&2
  exit 2
fi

mkdir -p "$UNIT_DIR"
install -m 644 "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl --user daemon-reload
systemctl --user enable arvor-mlflow.service
systemctl --user restart arvor-mlflow.service

if ! "$VENV_PYTHON" "$HEALTH" --env-file "$CLIENT_ENV" --wait 60; then
  journalctl --user -u arvor-mlflow.service -n 40 --no-pager >&2 || true
  exit 1
fi

systemctl --user --no-pager status arvor-mlflow.service | sed -n '1,12p'
