FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GOOGLE_APPLICATION_CREDENTIALS=/app/json/tell5_key.json

RUN sed -i 's|/json/tell5|/app/json/tell5|g' .env 2>/dev/null || true

RUN groupadd -r tell5 && useradd -r -g tell5 -d /app -s /sbin/nologin tell5 && \
    chown -R tell5:tell5 /app

USER tell5

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:${PORT:-8000}/healthz || exit 1

EXPOSE 8000

CMD uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000}
