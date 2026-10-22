# Image built from a trusted, reviewed revision — NEVER from an unreviewed PR.
# Build twice: --build-arg PYTHON_VERSION=3.12 and 3.14.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git nodejs ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/arvor-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/arvor-requirements.txt \
    playwright==1.58.0 pip-audit==2.10.1 && \
    python -m playwright install --with-deps chrome
WORKDIR /workspace
