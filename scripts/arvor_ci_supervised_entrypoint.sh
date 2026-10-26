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
# Verify candidate's exact direct pins against installed distributions audited
# inside the immutable Docker image; never resolve/install anything at runtime.
for python_bin in /opt/arvor/py312/bin/python /opt/arvor/py314/bin/python; do
  "$python_bin" - <<'PY'
from importlib import metadata
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pins = {}
for raw in Path("/workspace/requirements.txt").read_text(encoding="utf-8").splitlines():
    line = raw.split("#", 1)[0].strip()
    if not line:
        continue
    try:
        requirement = Requirement(line)
    except Exception:
        raise SystemExit("CI: invalid requirement declaration") from None
    specifications = list(requirement.specifier)
    if (requirement.url or requirement.marker or len(specifications) != 1
            or specifications[0].operator != "=="
            or "*" in specifications[0].version):
        raise SystemExit("CI: only exact unconditional version pins are supported")
    name = canonicalize_name(requirement.name)
    expected = specifications[0].version
    if name in pins and pins[name] != expected:
        raise SystemExit("CI: conflicting pinned versions")
    pins[name] = expected
    try:
        actual = metadata.version(name)
    except metadata.PackageNotFoundError:
        raise SystemExit("RECONSTRUCTION_IMAGE_REQUISE: candidate package absent: " + name) from None
    if actual != expected:
        raise SystemExit("RECONSTRUCTION_IMAGE_REQUISE: candidate version differs: " + name)

    # Verify that requested optional extras are also present and compatible.
    for extra in requirement.extras:
        for child in metadata.requires(name) or ():
            dependency = Requirement(child)
            if dependency.marker and dependency.marker.evaluate({"extra": extra}):
                try:
                    installed = metadata.version(dependency.name)
                except metadata.PackageNotFoundError:
                    raise SystemExit("RECONSTRUCTION_IMAGE_REQUISE: dependency absent for extra: " + extra) from None
                if dependency.specifier and installed not in dependency.specifier:
                    raise SystemExit("RECONSTRUCTION_IMAGE_REQUISE: incompatible dependency for extra: " + extra)
if not pins:
    raise SystemExit("CI: empty requirements")
print("CI preflight: exact direct pins and extras match audited image")
PY
done
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
