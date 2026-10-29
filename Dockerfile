FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser api ./api
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser data/clean.parquet ./data/clean.parquet
RUN python -m src.train --train-data data/clean.parquet
COPY --from=frontend-build --chown=appuser:appuser /app/frontend/dist ./frontend/dist

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
