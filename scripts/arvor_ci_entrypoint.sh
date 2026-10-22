#!/bin/sh
# Ephemeral PG16 sandbox: UID 999, no network, host socket or business mounts.
set -eu
umask 077
[ "$(id -u)" = 999 ] || { echo 'wrong sandbox uid'; exit 2; }
[ "$ARVOR_CI_ISOLATED" = 1 ] || { echo 'sandbox marker missing'; exit 2; }
[ ! -e /var/run/docker.sock ] || { echo 'docker socket exposed'; exit 2; }
[ ! -e /workspace/.env ] || { echo 'candidate includes .env'; exit 2; }
[ -r /trusted/arvor_local_ci.py ] || { echo 'trusted controller missing'; exit 2; }
[ -x /opt/arvor/py312/bin/python ] && [ -x /opt/arvor/py314/bin/python ] || { echo 'Python matrix missing'; exit 2; }
command -v initdb >/dev/null 2>&1 || { echo 'Postgres 16 initdb missing'; exit 2; }
command -v pg_ctl >/dev/null 2>&1 || { echo 'Postgres 16 pg_ctl missing'; exit 2; }
cd /workspace
# Docker source checkout belongs to the host, not to uid 999.
git config --global --add safe.directory /workspace
mkdir -p /tmp/audit-cache
# The image build grants UID 999 read access to the prewarmed cache.
# Do not use cp -a: it preserves root-owned modes and can fail under --user 999.
[ -r /opt/arvor/audit-cache ] || { echo 'pip-audit cache unreadable by sandbox UID'; exit 2; }
cp -R /opt/arvor/audit-cache/. /tmp/audit-cache/
initdb -D /var/lib/postgresql/data --auth-local=trust --auth-host=trust --no-sync >/dev/null
pg_ctl -D /var/lib/postgresql/data -o '-c listen_addresses=127.0.0.1 -c unix_socket_directories=/run/postgresql' -w start >/dev/null
trap 'pg_ctl -D /var/lib/postgresql/data -m immediate stop >/dev/null 2>&1 || true' EXIT
createuser -h 127.0.0.1 -s po_test
createdb -h 127.0.0.1 -O po_test po_test
export PO_TEST_DATABASE_URL='postgresql://po_test:ephemeral_ci_only@127.0.0.1:5432/po_test'
export TRACE_TEST_DATABASE_URL="$PO_TEST_DATABASE_URL"
export PO_ALLOW_TEST_MIGRATION=yes
export PATH="/opt/arvor/py314/bin:/usr/local/bin:/usr/bin:/bin"
exec /opt/arvor/py314/bin/python /trusted/arvor_local_ci.py \
  --checkout /workspace --sha "$1" --base-sha "$2" --pr "$3" \
  --python312 /opt/arvor/py312/bin/python --python314 /opt/arvor/py314/bin/python \
  --output /evidence
