#!/bin/sh
# Persistent disposable DB process for host-supervised Docker exec gates.
# IMPORTANT: no evidence output volume is ever mounted inside this container.
set -eu
umask 077
[ "$(id -u)" = 999 ] || { echo "SUPERVISOR: wrong UID"; exit 2; }
[ "${ARVOR_CI_ISOLATED:-}" = 1 ] || { echo "SUPERVISOR: missing isolation marker"; exit 2; }
[ ! -e /var/run/docker.sock ] || { echo "SUPERVISOR: docker socket present"; exit 2; }
[ ! -e /workspace/.env ] || { echo "SUPERVISOR: candidate contains .env"; exit 2; }
[ -r /trusted/arvor_local_ci.py ] && [ -r /trusted/arvor_ci_gate.py ] || exit 2
[ "${PLAYWRIGHT_BROWSERS_PATH:-}" = /opt/arvor/playwright-browsers ] || exit 2
command -v initdb >/dev/null 2>&1 || exit 2
command -v pg_ctl >/dev/null 2>&1 || exit 2
cd /workspace
git config --global --add safe.directory /workspace
initdb -D /var/lib/postgresql/data --auth-local=trust --auth-host=trust --no-sync >/dev/null
pg_ctl -D /var/lib/postgresql/data -o '-c listen_addresses=127.0.0.1 -c unix_socket_directories=/run/postgresql' -w start >/dev/null
createuser -h 127.0.0.1 -s po_test
createdb -h 127.0.0.1 -O po_test po_test
cleanup() {
  pg_ctl -D /var/lib/postgresql/data -m immediate stop >/dev/null 2>&1 || true
}
trap cleanup EXIT
echo "ARVOR_HOST_SUPERVISOR_DB_READY"
# Lifecycle belongs only to trusted host docker stop, never to candidate code.
while :; do
  sleep 60 &
  wait "$!" || true
done
