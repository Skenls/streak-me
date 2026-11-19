FROM node:26.13.1-bookworm-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.15.2-slim AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

FROM python:3.15.2-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WEB_DIST=/app/web/dist
COPY --from=dependencies /app/.venv /app/.venv
COPY streakme/ ./streakme/
COPY --from=frontend /web/dist ./web/dist/
USER 65534:65534
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "streakme"]
