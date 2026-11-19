import asyncio
import re
from datetime import UTC, datetime, timedelta
from functools import partial
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
    "style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self' {socket_origin}; "
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


async def set_response_headers(request, response, *, socket_origin):
    response.headers["Content-Security-Policy"] = CONTENT_POLICY.format(socket_origin=socket_origin)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path.startswith("/assets/") and response.status in {200, 206, 304} and ASSET_HASH.search(request.path):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers.setdefault("Cache-Control", "no-store")



def create_app(db: Database, static: Path, token: str, username: str, origin: str):
    sockets: set[web.WebSocketResponse] = set()

    def identity(proof):
        if not isinstance(proof, str) or len(proof) > 4092:
            raise web.HTTPUnauthorized()
        try:
            init = safe_parse_webapp_init_data(token, proof)
            age = datetime.now(UTC) - init.auth_date
            if not init.user or age >= INIT_DATA_TTL or age < -timedelta(minutes=1):
                raise ValueError("Expired or incomplete init data")
        except (ValueError, TypeError, OverflowError) as error:
            raise web.HTTPUnauthorized() from error
        return init

    def validate(request):
        value = request.headers.get("Authorization", "")
        if not value.startswith("tma "):
            raise web.HTTPUnauthorized()
        return identity(value[4:]).user

    def json(data, *, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    async def health(request):
        if request.remote not in {"127.0.0.1", "::1"}:
            raise web.HTTPNotFound()
        await db.check()
        return json({"ok": True})

    async def pairs(request):
        user = validate(request)
        if request.query.get("refresh") != "1":
            await db.save_profile(user)
        snapshot = db.updates.snapshot
        return json({
            "snapshot": snapshot,
            "streaks": await db.list(user.id),
            "me": {"name": user.first_name, "photoUrl": telegram_photo(user.photo_url)},
        })

    async def confirm(request):
        user = validate(request)
        pair = await db.get(int(request.match_info["id"]), user.id, action="confirm")
        if pair is None:
            raise web.HTTPNotFound()
        return json(pair)

    async def restore(request):
        user = validate(request)
        pair = await db.get(int(request.match_info["id"]), user.id, action="restore")
        if pair is None:
            raise web.HTTPNotFound()
        return json(pair)

    async def delete(request):
        user = validate(request)
        if not await db.delete(int(request.match_info["id"]), user.id):
            raise web.HTTPNotFound()
        return web.Response(status=204)

    async def invite(request):
        user = validate(request)
        await db.save_profile(user)
        return json({"url": invite_link(username, await db.invite_code(user.id))})

    async def live(request):
        if request.headers.get("Origin") != origin:
            raise web.HTTPForbidden()
        if len(sockets) >= 128:
            raise web.HTTPServiceUnavailable(headers={"Retry-After": "60"})
        socket = web.WebSocketResponse(heartbeat=60, compress=False, max_msg_size=8192, timeout=3)
        sockets.add(socket)
        try:
            await socket.prepare(request)
            try:
                async with asyncio.timeout(5):
                    message = await socket.receive_json()
                if not isinstance(message, dict):
                    raise ValueError("Invalid greeting")
                init = identity(message.get("proof"))
            except (TimeoutError, ValueError, TypeError, web.HTTPUnauthorized):
                await socket.close(code=4401)
                return socket

            with db.updates.watch(init.user.id) as pending:
                if pending is None:
                    await socket.close(code=1013)
                    return socket

                async def forward():
                    while True:
                        await pending.wait()
                        pending.clear()
                        await socket.send_str("refresh")

                await socket.send_str("ready")
                if message.get("snapshot") != db.updates.snapshot:
                    pending.set()
                sender = asyncio.create_task(forward())
                try:
                    lifetime = init.auth_date + INIT_DATA_TTL - datetime.now(UTC)
                    async with asyncio.timeout(lifetime.total_seconds()):
                        async for _ in socket:
                            await socket.close(code=1008)
                            break
                except TimeoutError:
                    await socket.close(code=4401)
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
        except ConnectionError:
            pass
        finally:
            sockets.discard(socket)
        return socket

    async def index(request):
        return web.FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    app = web.Application(middlewares=[database_busy])
    socket_origin = origin.replace("https://", "wss://", 1)
    app.on_response_prepare.append(partial(set_response_headers, socket_origin=socket_origin))

    async def close_sockets(app):
        await asyncio.gather(*(socket.close(code=1001) for socket in tuple(sockets)), return_exceptions=True)

    async def close_database(app):
        await db.close()

    app.on_shutdown.append(close_sockets)
    app.on_cleanup.append(close_database)
    app.add_routes([
        web.get("/healthz", health),
        web.get("/api/streaks", pairs),
        web.get("/api/live", live, allow_head=False),
        web.post(r"/api/streaks/{id:[1-9][0-9]{0,17}}/confirm", confirm),
        web.post(r"/api/streaks/{id:[1-9][0-9]{0,17}}/restore", restore),
        web.delete(r"/api/streaks/{id:[1-9][0-9]{0,17}}", delete),
        web.post("/api/invite", invite),
        web.get("/", index),
    ])
    assets = static / "assets"
    if assets.is_dir():
        app.router.add_static("/assets", assets)
    return app
