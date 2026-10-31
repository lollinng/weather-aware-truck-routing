# One image serves both the API and the built React app (WhiteNoise serves the static files).

FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# One worker keeps the in-process forecast cache shared; requests are I/O-bound, so threads scale.
CMD gunicorn config.wsgi --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 90 --access-logfile -
