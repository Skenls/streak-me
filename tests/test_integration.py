import asyncio
import hmac
import json
import os
import secrets
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import AnswerCallbackQuery, AnswerInlineQuery, SendMessage
from aiogram.types import Update
from aiohttp.test_utils import TestClient, TestServer

from streakme.bot import dispatcher
from streakme.db import Database
from streakme.server import create_app

TOKEN = "1234:integration-test"
USERNAME = "streakme_test_bot"
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
        await self.db.initialize()
        app = create_app(self.db, Path("web/dist"), TOKEN, USERNAME)
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

    async def accept(self, user, start):
        return await self.update(message={
            "message_id": 1, "date": int(time.time()), "from": user,
            "chat": {"id": user["id"], "type": "private"},
            "text": f"/start {start}", "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        })

    async def test_invite_access_and_concurrent_confirmation(self):
        response = await self.client.get("/api/streaks")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/api/streaks", headers=auth(self.a, seconds_ago=90_000))
        self.assertEqual(response.status, 401)

        inline = await self.update(inline_query={"id": "1", "from": self.a, "query": "", "offset": ""})
        self.assertIsInstance(inline, AnswerInlineQuery)
        self.assertEqual(len(inline.results), 3)
        inline_url = inline.results[0].reply_markup.inline_keyboard[0][0].url
        self.assertIn(f"https://t.me/{USERNAME}?start=join_", inline_url)

        invite = await self.client.post("/api/invite", headers=auth(self.a))
        self.assertEqual(invite.status, 200)
        url = (await invite.json())["url"]
        start = parse_qs(urlsplit(url).query)["start"][0]
        self.assertIn("твоё", (await self.accept(self.a, start)).text)
        accepted = await self.accept(self.b, start)
        self.assertIsInstance(accepted, SendMessage)
        self.assertIn("создан", accepted.text)
        self.assertIn("создан", (await self.accept(self.b, start)).text)
        self.assertIn("уже приняли", (await self.accept(self.c, start)).text)

        response = await self.client.get("/api/streaks", headers=auth(self.a))
        pair, = (await response.json())["streaks"]
        self.assertEqual(pair["friend"]["id"], self.b["id"])
        path = f"/api/streaks/{pair['id']}/confirm"
        response = await self.client.post(path, headers=auth(self.c))
        self.assertEqual(response.status, 404)

        confirmations = await asyncio.gather(
            *(self.client.post(path, headers=auth(user)) for user in (self.a, self.b, self.b))
        )
        self.assertTrue(all(response.status == 200 for response in confirmations))
        self.assertEqual(sorted([(await response.json())["days"] for response in confirmations])[-1], 1)
        final = await self.db.get(pair["id"], self.a["id"])
        self.assertEqual((final["days"], final["confirmed"], final["friendConfirmed"]), (1, True, True))

        inline = await self.update(inline_query={"id": "2", "from": self.a, "query": "Mira", "offset": ""})
        self.assertEqual([result.id for result in inline.results], [
            "invite", f"confirm:{pair['id']}", f"status:{pair['id']}",
        ])
        for user, action, expected in (
            (self.c, "confirm", "Только участники"),
            (self.b, "confirm", "Сегодня оба"),
            (self.a, "status", "Дней подряд: 1"),
        ):
            answer = await self.update(callback_query={
                "id": "3", "from": user, "chat_instance": "instance",
                "inline_message_id": "inline-id", "data": f"{action}:{pair['id']}",
            })
            self.assertIsInstance(answer, AnswerCallbackQuery)
            self.assertIn(expected, answer.text)
