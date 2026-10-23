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
# Playwright's default headless mode requires its own bundled shell binary,
# not the Debian system Chromium. Validate it before database/test startup.
[ "${PLAYWRIGHT_BROWSERS_PATH:-}" = "/opt/arvor/playwright-browsers" ] || {
  echo 'CI preflight: browser path not pinned'; exit 2;
}
/opt/arvor/py312/bin/python - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    browser.close()
print("CI preflight: Playwright Chromium headless shell launched")
PY
# Voice timeline tests execute a deterministic local Piper stub in /tmp.
# Check executable tmpfs explicitly; refuse silent skips or modified PR tests.
/opt/arvor/py312/bin/python - <<'PY'
import pathlib
import shutil
import subprocess
import tempfile

with tempfile.TemporaryDirectory(prefix="arvor-tts-probe-") as temp:
    candidate = pathlib.Path(temp) / "piper-stub"
    candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    candidate.chmod(0o700)
    if shutil.which(str(candidate)) != str(candidate):
        raise SystemExit("CI preflight: executable Piper stub unavailable in /tmp")
    subprocess.run([str(candidate)], check=True, timeout=3)
print("CI preflight: Piper stub executable and ffmpeg path checked")
PY
cd /workspace
# /tmp is mounted as an ephemeral tmpfs, hiding build-time files there.
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
        raise SystemExit("CI: candidate requirement missing in audited image: " + name) from None
    if actual != expected:
        raise SystemExit("CI: candidate pin differs from audited image: " + name)

    # Verify that requested optional extras are also present and compatible.
    for extra in requirement.extras:
        for child in metadata.requires(name) or ():
            dependency = Requirement(child)
            if dependency.marker and dependency.marker.evaluate({"extra": extra}):
                try:
                    installed = metadata.version(dependency.name)
                except metadata.PackageNotFoundError:
                    raise SystemExit("CI: missing dependency for requested extra: " + extra) from None
                if dependency.specifier and installed not in dependency.specifier:
                    raise SystemExit("CI: incompatible dependency for requested extra: " + extra)
if not pins:
    raise SystemExit("CI: empty requirements")
print("CI preflight: exact direct pins and extras match audited image")
PY
done
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
