# syntax=docker/dockerfile:1
# Build once from reviewed source, then run ONLY by immutable image ID.
# This Dockerfile is a preparation artefact; it has not been built on Arvor PC.
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

# Prewarm the vulnerability cache during this trusted networked build.
# The candidate runtime has --network=none: cache misses then fail closed.
RUN /opt/arvor/py312/bin/python -m pip_audit -r /tmp/arvor-requirements.txt \
      --progress-spinner off --cache-dir /opt/arvor/audit-cache

# Browser fixtures currently use Playwright channel="chrome". The symlink
# must be verified with a real browser run before this image is approved.
ENV PATH="/usr/lib/postgresql/16/bin:/opt/arvor/py314/bin:/usr/local/bin:/usr/bin:/bin"
ENTRYPOINT []
