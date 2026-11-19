import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web
from psycopg import OperationalError
from psycopg.errors import QueryCanceled
from psycopg_pool import PoolTimeout, TooManyRequests

from .bot import invite_link
from .db import Database, telegram_photo

INIT_DATA_TTL = timedelta(hours=1)
ASSET_HASH = re.compile(r"[-][A-Za-z0-9_-]{8}\.(?:css|js|woff2|webp)$")
CONTENT_POLICY = (
    "default-src 'none'; script-src 'self' https://telegram.org/js/telegram-web-app.js; "
    "style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; "
    "img-src 'self' https://t.me https://telegram-cdn.org https://*.telegram-cdn.org "
    "https://*.telesco.pe; base-uri 'none'; form-action 'none'; "
    "frame-ancestors https://web.telegram.org"
)


@web.middleware
async def database_busy(request, handler):
    try:
        return await handler(request)
    except (OperationalError, PoolTimeout, TooManyRequests, QueryCanceled) as error:
        raise web.HTTPServiceUnavailable(headers={"Retry-After": "2"}) from error


async def set_response_headers(request, response):
    response.headers["Content-Security-Policy"] = CONTENT_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path.startswith("/assets/") and response.status in {200, 206, 304} and ASSET_HASH.search(request.path):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers.setdefault("Cache-Control", "no-store")



def create_app(db: Database, static: Path, token: str, username: str):
    def validate(request):
        value = request.headers.get("Authorization", "")
        if not value.startswith("tma ") or len(value) > 4096:
            raise web.HTTPUnauthorized()
        try:
            init = safe_parse_webapp_init_data(token, value.removeprefix("tma "))
            age = datetime.now(UTC) - init.auth_date
            if not init.user or age > INIT_DATA_TTL or age < -timedelta(minutes=1):
                raise ValueError("Expired or incomplete init data")
        except (ValueError, TypeError, OverflowError) as error:
            raise web.HTTPUnauthorized() from error
        return init.user

    def json(data, *, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    async def health(request):
        if request.remote not in {"127.0.0.1", "::1"}:
            raise web.HTTPNotFound()
        await db.check()
        return json({"ok": True})

    async def pairs(request):
        user = validate(request)
        await db.save_profile(user)
        return json({
            "streaks": await db.list(user.id),
            "me": {"name": user.first_name, "photoUrl": telegram_photo(user.photo_url)},
        })

    async def confirm(request):
        user = validate(request)
        pair = await db.get(int(request.match_info["id"]), user.id, confirm=True)
        if pair is None:
            raise web.HTTPNotFound()
        return json(pair)

    async def invite(request):
        user = validate(request)
        await db.save_profile(user)
        return json({"url": invite_link(username, user.id, token)})

    async def index(request):
        return web.FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    app = web.Application(middlewares=[database_busy])
    app.on_response_prepare.append(set_response_headers)

    async def close_database(app):
        await db.close()

    app.on_cleanup.append(close_database)
    app.add_routes([
        web.get("/healthz", health),
        web.get("/api/streaks", pairs),
        web.post(r"/api/streaks/{id:[1-9][0-9]{0,17}}/confirm", confirm),
        web.post("/api/invite", invite),
        web.get("/", index),
    ])
    assets = static / "assets"
    if assets.is_dir():
        app.router.add_static("/assets", assets)
    return app
