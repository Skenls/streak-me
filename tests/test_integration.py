import asyncio
import hmac
import json
import os
import secrets
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import AnswerCallbackQuery, AnswerInlineQuery, SendMessage
from aiogram.types import Update
from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from streakme.bot import dispatcher
from streakme.db import Database
from streakme.reminders import remind
from streakme.server import create_app

TOKEN = "1234:integration-test"
USERNAME = "streakme_test_bot"
ORIGIN = "https://streak.example.com"
DSN = os.getenv("TEST_DATABASE_URL")


class RecordingSession(AiohttpSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        return True


def auth(user, *, seconds_ago=0):
    fields = {
        "auth_date": str(int(time.time()) - seconds_ago),
        "user": json.dumps(user, separators=(",", ":")),
    }
    check = "\n".join(f"{name}={value}" for name, value in sorted(fields.items()))
    key = hmac.digest(b"WebAppData", TOKEN.encode(), "sha256")
    fields["hash"] = hmac.digest(key, check.encode(), "sha256").hex()
    return {"Authorization": "tma " + urlencode(fields)}


@unittest.skipUnless(DSN, "Set TEST_DATABASE_URL to a disposable PostgreSQL database")
class IntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(DSN)
        await self.db.open()
        self.addAsyncCleanup(self.db.close)
        app = create_app(self.db, Path("web/dist"), TOKEN, USERNAME, ORIGIN)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.session = RecordingSession()
        self.bot = Bot(TOKEN, session=self.session)
        self.addAsyncCleanup(self.session.close)
        self.dp = dispatcher(self.db, USERNAME, TOKEN, "https://streak.example.com/")
        self.a, self.b, self.c = [
            {"id": 2**42 + secrets.randbits(40), "first_name": name, "is_bot": False}
            for name in ("Luna", "Mira", "Nick")
        ]

    async def update(self, **fields):
        await self.dp.feed_update(self.bot, Update.model_validate({"update_id": 1, **fields}))
        return self.session.calls[-1]

    async def command(self, user, text):
        return await self.update(message={
            "message_id": 1, "date": int(time.time()), "from": user,
            "chat": {"id": user["id"], "type": "private"},
            "text": text, "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}],
        })

    async def accept(self, user, start):
        return await self.command(user, f"/start {start}")

    async def invite(self, user):
        response = await self.client.post("/api/invite", headers=auth(user))
        self.assertEqual(response.status, 200)
        return (await response.json())["url"]

    async def callbacks(self, user, action, *, chat="instance"):
        return await self.update(callback_query={
            "id": "3", "from": user, "chat_instance": chat,
            "inline_message_id": "inline-id", "data": action,
        })

    @staticmethod
    def start_value(url):
        return parse_qs(urlsplit(url).query)["start"][0]

    async def test_invite_access_and_concurrent_confirmation(self):
        response = await self.client.get("/api/streaks")
        self.assertEqual(response.status, 401)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors https://web.telegram.org", response.headers["Content-Security-Policy"])
        response = await self.client.get("/api/streaks", headers=auth(self.a, seconds_ago=3_601))
        self.assertEqual(response.status, 401)
        response = await self.client.get("/api/streaks", headers=auth(self.a, seconds_ago=-61))
        self.assertEqual(response.status, 401)
        response = await self.client.get("/api/streaks", headers=auth({**self.a, "photo_url": "https://example.org/photo"}))
        self.assertIsNone((await response.json())["me"]["photoUrl"])

        inline = await self.update(inline_query={
            "id": "1", "from": self.a, "query": "", "offset": "", "chat_type": "group",
        })
        self.assertIsInstance(inline, AnswerInlineQuery)
        self.assertEqual(len(inline.results), 1)
        group_buttons = inline.results[0].reply_markup.inline_keyboard
        self.assertEqual(len(group_buttons), 1)
        inline_url = group_buttons[0][0].url

        url = await self.invite(self.a)
        self.assertEqual(inline_url, url)
        self.assertEqual(await self.invite(self.a), url)
        start = self.start_value(url)
        self.assertIn("твоё", (await self.accept(self.a, start)).text)
        for user in (self.b, self.c, self.b):
            accepted = await self.accept(user, start)
            self.assertIsInstance(accepted, SendMessage)
            self.assertIn("готов", accepted.text)

        reset = await self.command(self.a, "/reset")
        new_url = await self.invite(self.a)
        self.assertNotEqual(new_url, url)
        self.assertIn(new_url, reset.text)
        self.assertIn("недействительна", (await self.accept(self.b, start)).text)

        pairs = await self.db.list(self.a["id"])
        pair = next(row for row in pairs if row["friend"]["id"] == self.b["id"])
        other = next(row for row in pairs if row["friend"]["id"] == self.c["id"])
        self.assertEqual(pair["status"], "frozen")
        path = f"/api/streaks/{pair['id']}"
        for suffix in ("/confirm", "/restore"):
            response = await self.client.post(path + suffix, headers=auth(self.c))
            self.assertEqual(response.status, 404)
        response = await self.client.delete(path, headers=auth(self.c))
        self.assertEqual(response.status, 404)

        inline = await self.update(inline_query={
            "id": "2", "from": self.a, "query": "Mira", "offset": "", "chat_type": "private",
        })
        self.assertEqual([result.id for result in inline.results], ["invite"])
        status, confirm = inline.results[0].reply_markup.inline_keyboard[1]
        reply = await self.callbacks(self.a, status.callback_data)
        self.assertIn("Пусть друг", reply.text)
        reply = await self.callbacks(self.b, confirm.callback_data)
        self.assertIsInstance(reply, AnswerCallbackQuery)
        self.assertIn("очередь друга", reply.text)
        reply = await self.callbacks(self.c, confirm.callback_data)
        self.assertIn("нет общей серии", reply.text)

        confirmations = await asyncio.gather(
            *(self.client.post(path + "/confirm", headers=auth(user)) for user in (self.a, self.b, self.b))
        )
        self.assertTrue(all(response.status == 200 for response in confirmations))
        self.assertEqual(max([(await response.json())["days"] for response in confirmations]), 1)
        final = await self.db.get(pair["id"], self.a["id"])
        self.assertEqual((final["days"], final["status"]), (1, "active"))
        self.assertEqual((await self.db.get(other["id"], self.a["id"]))["days"], 0)
        reply = await self.callbacks(self.a, status.callback_data)
        self.assertIn("Сегодня оба", reply.text)

        response = await self.client.delete(path, headers=auth(self.b))
        self.assertEqual(response.status, 204)
        self.assertEqual(await self.db.list(self.b["id"]), [])
        self.assertEqual([row["id"] for row in await self.db.list(self.a["id"])], [other["id"]])

    async def test_lifecycle_quota_and_reminder(self):
        await self.accept(self.b, self.start_value(await self.invite(self.a)))
        pair, = await self.db.list(self.a["id"])
        pair_id = pair["id"]
        now = datetime.now(UTC)
        today = now.date()
        yesterday = today - timedelta(days=1)
        path = f"/api/streaks/{pair_id}"

        async with self.db.pool.connection() as conn:
            await conn.execute(
                "UPDATE streaks SET days=11, completed_day=%s, low_day=%s WHERE id=%s",
                (yesterday, today, pair_id),
            )
        await remind(self.db, self.bot, "https://streak.example.com/", now.replace(hour=18, minute=59))
        self.assertEqual(len(self.session.calls), 1)  # Only the earlier /start reply.
        await remind(self.db, self.bot, "https://streak.example.com/", now.replace(hour=19, minute=0))
        sent = self.session.calls[-1]
        self.assertIsInstance(sent, SendMessage)
        self.assertEqual(sent.chat_id, max(self.a["id"], self.b["id"]))
        await remind(self.db, self.bot, "https://streak.example.com/", now.replace(hour=19, minute=1))
        self.assertEqual(len(self.session.calls), 2)

        async with self.db.pool.connection() as conn:
            await conn.execute(
                "UPDATE streaks SET completed_day=%s, low_day=NULL, restore_month=%s, restore_count=4 WHERE id=%s",
                (today - timedelta(days=2), today.replace(day=1), pair_id),
            )
        stale = await self.client.post(path + "/confirm", headers=auth(self.a))
        self.assertEqual((await stale.json())["status"], "lost")
        restorations = await asyncio.gather(
            *(self.client.post(path + "/restore", headers=auth(user)) for user in (self.a, self.b))
        )
        for response in restorations:
            updated = await response.json()
            self.assertEqual((updated["days"], updated["status"], updated["restoresLeft"]), (11, "frozen", 0))

        async with self.db.pool.connection() as conn:
            await conn.execute(
                "UPDATE streaks SET completed_day=%s WHERE id=%s",
                (today - timedelta(days=2), pair_id),
            )
        self.assertIsNone(await self.db.get(pair_id, self.b["id"]))
        await self.db.expire(today)
        async with self.db.pool.connection() as conn:
            row = await conn.execute("SELECT id FROM streaks WHERE id=%s", (pair_id,))
            self.assertIsNone(await row.fetchone())
        await self.accept(self.b, self.start_value(await self.invite(self.a)))
        new, = await self.db.list(self.a["id"])
        self.assertNotEqual(new["id"], pair_id)
        self.assertEqual(new["days"], 0)

        # A loss in a new calendar month uses the new quota, even when the old month was full.
        first = today.replace(day=1)
        previous_month = first - timedelta(days=1)
        async with self.db.pool.connection() as conn:
            await conn.execute(
                "UPDATE streaks SET days=3, completed_day=%s, restore_month=%s, restore_count=5 WHERE id=%s",
                (previous_month - timedelta(days=1), previous_month.replace(day=1), new["id"]),
            )
        await self.db.expire(first)
        carried = await self.db.get(new["id"], self.a["id"])
        self.assertEqual((carried["status"], carried["restoresLeft"]), ("lost", 5))


    async def test_live_updates_are_scoped_and_catch_up_after_reconnect(self):
        await self.accept(self.b, self.start_value(await self.invite(self.a)))
        pair, = await self.db.list(self.a["id"])

        async def revision(user):
            response = await self.client.get("/api/streaks?refresh=1", headers=auth(user))
            return (await response.json())["snapshot"]

        async def watch(user, snapshot):
            ws = await self.client.ws_connect("/api/live", headers={"Origin": ORIGIN})
            self.addAsyncCleanup(ws.close)
            await ws.send_json({"proof": auth(user)["Authorization"][4:], "snapshot": snapshot})
            self.assertEqual(await ws.receive_str(timeout=2), "ready")
            return ws

        with self.assertRaises(WSServerHandshakeError) as rejected:
            await self.client.ws_connect("/api/live", headers={"Origin": "https://unknown.example"})
        self.assertEqual(rejected.exception.status, 403)
        async with self.client.ws_connect("/api/live", headers={"Origin": ORIGIN}) as denied:
            await denied.send_json({"proof": "invalid"})
            message = await denied.receive(timeout=2)
            self.assertEqual((message.type, message.data), (WSMsgType.CLOSE, 4401))

        initial = await revision(self.b)
        friend = await watch(self.b, initial)
        unrelated = await watch(self.c, initial)
        response = await self.client.post(f"/api/streaks/{pair['id']}/confirm", headers=auth(self.a))
        self.assertEqual(response.status, 200)
        self.assertEqual(await friend.receive_str(timeout=2), "refresh")
        with self.assertRaises(TimeoutError):
            await unrelated.receive(timeout=0.05)

        await self.command({**self.a, "first_name": "Луна"}, "/start")
        self.assertEqual(await friend.receive_str(timeout=2), "refresh")
        response = await self.client.get("/api/streaks?refresh=1", headers=auth(self.b))
        self.assertEqual((await response.json())["streaks"][0]["friend"]["name"], "Луна")

        await friend.close()
        self.assertNotEqual(await revision(self.b), initial)
        reconnected = await watch(self.b, initial)
        self.assertEqual(await reconnected.receive_str(timeout=2), "refresh")
        response = await self.client.delete(f"/api/streaks/{pair['id']}", headers=auth(self.a))
        self.assertEqual(response.status, 204)
        self.assertEqual(await reconnected.receive_str(timeout=2), "refresh")
        await unrelated.close()
        await self.db.expire(datetime.now(UTC).date())
        self.assertEqual(await reconnected.receive_str(timeout=2), "refresh")
