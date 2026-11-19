FROM node:26.13.1-bookworm-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.15.2-alpine3.24 AS python-base
RUN apk upgrade --no-cache

FROM python-base AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

FROM python-base AS runtime
# PostgreSQL is the only database. Keep the other shared libraries from the Python image.
RUN set -- $(apk info -R .python-rundeps | awk '/^so:/ && !/^so:libsqlite3[.]/') \
    && test "$#" -gt 0 \
    && apk add --no-network --virtual .streakme-rundeps "$@" \
    && apk del --no-network .python-rundeps \
    && ! apk info -e sqlite-libs \
    && rm /usr/local/lib/python3.15/lib-dynload/_sqlite3.*.so
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WEB_DIST=/app/web/dist
COPY --from=dependencies /app/.venv /app/.venv
COPY streakme/ ./streakme/
COPY --from=frontend /web/dist ./web/dist/
RUN /app/.venv/bin/python -m compileall -q /usr/local/lib/python3.15 /app/.venv/lib /app/streakme
USER 65534:65534
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "streakme"]
