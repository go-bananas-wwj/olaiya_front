FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_APP_MODE=showcase npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/python -m venv /app/.venv
COPY deploy/requirements.txt /app/deploy/requirements.txt
RUN .venv/bin/python -m pip install --no-cache-dir -r deploy/requirements.txt
COPY backend/app/ /app/backend/app/
COPY data/seed/ /app/data/seed/
COPY deploy/ /app/deploy/
COPY --from=frontend /build/web/ /app/web/
# Existing static mounts must exist even though they are outside the demo flow.
RUN mkdir -p lab/hero-demo/dist lab/wireframes /mnt/workspace/cfz
ENV PYTHONPATH=/app/backend \
    PYTHONUNBUFFERED=1 \
    CFZ_LLM_CHANNEL=cloud \
    CFZ_ROUNDTABLE_GROUNDED=true \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
    CMD .venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=4)"
CMD ["/app/.venv/bin/python", "-m", "deploy.bootstrap"]
