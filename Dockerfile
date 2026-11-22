FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1000 arvor && useradd --uid 1000 --gid arvor --no-create-home arvor
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY apps ./apps
COPY editorial ./editorial
COPY infrastructure ./infrastructure
COPY production ./production
COPY scripts/render_episode.py ./scripts/
COPY workflows ./workflows
COPY workers ./workers
COPY pilotage ./pilotage
USER 1000:1000
CMD ["uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
