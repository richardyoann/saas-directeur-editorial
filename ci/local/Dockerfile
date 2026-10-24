# syntax=docker/dockerfile:1
# Build once from reviewed source, then run ONLY by immutable image ID.
# Each immutable Docker build needs a fresh security audit and WSL acceptance.
FROM ghcr.io/astral-sh/uv:0.12.21 AS uv
FROM postgres:16-bookworm

COPY --from=uv /uv /uvx /usr/local/bin/
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git nodejs ffmpeg chromium xz-utils \
      && rm -rf /var/lib/apt/lists/*

# Gitleaks 8.28.0 with checksum verified before extraction.
RUN curl -fLsS --retry 3 \
      https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_linux_x64.tar.gz \
      -o /tmp/gitleaks.tar.gz \
 && echo "a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb  /tmp/gitleaks.tar.gz" | sha256sum -c - \
 && tar -C /usr/local/bin -xzf /tmp/gitleaks.tar.gz gitleaks \
 && rm -f /tmp/gitleaks.tar.gz

ENV UV_PYTHON_INSTALL_DIR=/opt/arvor/pythons
ENV UV_PYTHON_PREFERENCE=only-managed
RUN uv python install 3.12 3.14 \
 && uv venv --python 3.12 /opt/arvor/py312 \
 && uv venv --python 3.14 /opt/arvor/py314

COPY requirements.txt /tmp/arvor-requirements.txt
COPY ci/local/requirements-ci.txt /tmp/arvor-requirements-ci.txt
RUN uv pip install --python /opt/arvor/py312/bin/python \
       -r /tmp/arvor-requirements.txt -r /tmp/arvor-requirements-ci.txt \
 && uv pip install --python /opt/arvor/py314/bin/python \
       -r /tmp/arvor-requirements.txt -r /tmp/arvor-requirements-ci.txt \
 && mkdir -p /opt/google/chrome \
 && ln -s /usr/bin/chromium /opt/google/chrome/chrome

# Playwright 1.58.0 needs its own exact-revision Chromium headless shell.
# Debian's /usr/bin/chromium is NOT the matching Playwright executable.
# Download and install system dependencies only at trusted image build time.
# This image is used with --network=none at candidate test runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/arvor/playwright-browsers
RUN /opt/arvor/py312/bin/python -m playwright install --with-deps --only-shell chromium \
 && chmod -R a+rX /opt/arvor/playwright-browsers

# Audit both complete installed environments with PyPI during TRUSTED image
# construction, while network access exists. Immutable snapshots are checked
# for exact packages/versions and expire after 24 h; no HTTP-cache dependency
# or external service is required during --network=none candidate execution.
COPY ci/local/audit_snapshot.py /opt/arvor/security/audit_snapshot.py
RUN /opt/arvor/py312/bin/python /opt/arvor/security/audit_snapshot.py --build \
 && chmod -R a+rX /opt/arvor/security

# Chromium headless-shell start is checked by the trusted sandbox preflight.
ENV PATH="/usr/lib/postgresql/16/bin:/opt/arvor/py314/bin:/usr/local/bin:/usr/bin:/bin"
ENTRYPOINT []
