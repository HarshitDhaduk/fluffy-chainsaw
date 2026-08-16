# One image, three services: the deploy script overrides APP_MODULE per
# Cloud Run service (agents / api / sandbox). Decoupling is at runtime via
# Pub/Sub, not at build time.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY lalfita ./lalfita
RUN pip install --no-cache-dir ".[cloud]"

ENV APP_MODULE=lalfita.agents.service:app \
    PORT=8080

CMD exec uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$PORT"
