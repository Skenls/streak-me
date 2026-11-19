import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web
from psycopg.conninfo import make_conninfo

from .bot import dispatcher
from .db import Database
from .server import create_app


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        message = super().format(record)
        token = os.environ.get("BOT_TOKEN")
        return message.replace(token, "[bot token]") if token else message


async def application():
    token = os.environ["BOT_TOKEN"]
    app_url = os.environ["APP_URL"]
    parsed = urlparse(app_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("APP_URL must be the HTTPS address of the Mini App root")

    dsn = os.getenv("DATABASE_URL") or make_conninfo(
        host="db", dbname="streakme", user="streakme_app", password=os.environ["APP_DB_PASSWORD"]
    )
    db = Database(dsn)
    static = Path(os.getenv("WEB_DIST", "web/dist"))
    bot = Bot(token)
    try:
        await db.open()
        me = await bot.get_me()
        if not me.supports_inline_queries:
            logging.warning("Enable inline mode using /setinline in BotFather.")
        app = create_app(db, static, token, me.username)
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="StreakMe", web_app=WebAppInfo(url=app_url))
        )
        dp = dispatcher(db, me.username, token, app_url)
    except BaseException:
        await bot.session.close()
        await db.close()
        raise

    async def polling_context(app):
        task = asyncio.create_task(
            dp.start_polling(
                bot, handle_signals=False, close_bot_session=False, tasks_concurrency_limit=16
            )
        )
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bot.session.close()

    app.cleanup_ctx.append(polling_context)
    return app


if __name__ == "__main__":
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(levelname)s:%(name)s:%(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    web.run_app(application(), host="0.0.0.0", port=8080, access_log=None)
