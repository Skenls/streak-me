import asyncio
import logging
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from .bot import open_app
from .db import Database

logger = logging.getLogger(__name__)
REMINDER_HOUR = 19


async def remind(db: Database, bot: Bot, app_url: str, now: datetime):
    if now.hour < REMINDER_HOUR:
        return
    day = now.date()
    waiting = await db.claim_reminders(day)
    for index, row in enumerate(waiting):
        if datetime.now(UTC).date() > day:
            return
        total = row["total"]
        text = (
            "🔥 Ты ещё не отметился. Продли огонёк до 00:00 UTC."
            if total == 1
            else f"🔥 Ждут твоей отметки: {total} огоньков. Отметься до 00:00 UTC."
        )
        try:
            await bot.send_message(row["id"], text, reply_markup=open_app(app_url), request_timeout=8)
        except TelegramRetryAfter as error:
            await db.release_reminders(day, [pending["id"] for pending in waiting[index:]])
            await asyncio.sleep(error.retry_after)
            return
        except TelegramForbiddenError:
            continue
        except TelegramAPIError as error:
            # Telegram may have accepted a request that timed out. Keep the claim to avoid repeats.
            logger.warning("Reminder delivery failed: %s", type(error).__name__)
        await asyncio.sleep(0.05)


async def maintenance(db: Database, bot: Bot, app_url: str):
    cleaned_on = None
    while True:
        now = datetime.now(UTC)
        try:
            if cleaned_on != now.date():
                await db.expire(now.date())
                cleaned_on = now.date()
            await remind(db, bot, app_url, now)
        except Exception:
            logger.exception("Streak maintenance failed")
        await asyncio.sleep(30 - datetime.now(UTC).second % 30)
