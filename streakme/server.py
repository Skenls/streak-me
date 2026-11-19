from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web
from psycopg import OperationalError

from .bot import invite_link
from .db import Database

INIT_DATA_TTL = timedelta(hours=24)


def create_app(db: Database, static: Path, token: str = "", username: str = ""):
    def validate(request):
        value = request.headers.get("Authorization", "")
        if not token or not value.startswith("tma "):
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
        try:
            await db.check()
        except OperationalError:
            return json({"ok": False}, status=503)
        return json({"ok": True})

    async def pairs(request):
        user = validate(request)
        await db.save_profile(user)
        return json({
            "streaks": await db.list(user.id),
            "me": {"name": user.first_name, "photoUrl": user.photo_url},
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

    app = web.Application()
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
