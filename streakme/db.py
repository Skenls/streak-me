from datetime import UTC, datetime
from pathlib import Path

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .rules import Confirmations, streak_status

PAIR_VIEW = """
    SELECT s.*, p.id AS friend_id, p.name, p.username, p.photo_url
    FROM streaks s JOIN profiles p ON p.id =
        CASE WHEN s.low_id = %(user)s THEN s.high_id ELSE s.low_id END
    WHERE %(user)s IN (s.low_id, s.high_id)
"""


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn

    async def connect(self):
        return await AsyncConnection.connect(self.dsn, row_factory=dict_row, connect_timeout=5)

    async def initialize(self):
        schema = Path(__file__).with_name("schema.sql").read_text()
        async with await self.connect() as conn:
            await conn.execute(schema)

    async def check(self):
        async with await self.connect() as conn:
            await conn.execute("SELECT 1")

    async def save_profile(self, user):
        name = " ".join(part for part in (user.first_name, user.last_name) if part)
        async with await self.connect() as conn:
            await conn.execute(
                """
                INSERT INTO profiles (id, name, username, photo_url) VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, username = EXCLUDED.username,
                    photo_url = COALESCE(EXCLUDED.photo_url, profiles.photo_url)
                """,
                (user.id, name, user.username, getattr(user, "photo_url", None)),
            )

    async def accept(self, token: str, inviter: int, receiver: int) -> bool:
        low, high = sorted((inviter, receiver))
        async with await self.connect() as conn:
            await conn.execute(
                "DELETE FROM claimed_invites WHERE claimed_at < now() - interval '7 days'"
            )
            claim = await conn.execute(
                """
                INSERT INTO claimed_invites (token, receiver_id) VALUES (%s, %s)
                ON CONFLICT (token) DO NOTHING
                """,
                (token, receiver),
            )
            if claim.rowcount == 0:
                previous = await conn.execute(
                    "SELECT receiver_id FROM claimed_invites WHERE token = %s", (token,)
                )
                return (await previous.fetchone())["receiver_id"] == receiver
            await conn.execute(
                """
                INSERT INTO streaks (low_id, high_id) VALUES (%s, %s)
                ON CONFLICT (low_id, high_id) DO NOTHING
                """,
                (low, high),
            )
            return True

    async def list(self, user: int):
        async with await self.connect() as conn:
            rows = await conn.execute(PAIR_VIEW + " ORDER BY s.id DESC", {"user": user})
            today = datetime.now(UTC).date()
            return [self.present(row, user, today) for row in await rows.fetchall()]

    async def get(self, pair_id: int, user: int, *, confirm: bool = False):
        async with await self.connect() as conn:
            query = PAIR_VIEW + " AND s.id = %(pair)s"
            if confirm:
                query += " FOR UPDATE OF s"
            result = await conn.execute(query, {"user": user, "pair": pair_id})
            row = await result.fetchone()
            if row is None:
                return None
            today = datetime.now(UTC).date()
            if confirm:
                previous = self.confirmations(row)
                state = previous.confirm(user == row["low_id"], today)
                if previous != state:
                    await conn.execute(
                        """
                        UPDATE streaks SET low_day = %s, high_day = %s, completed_day = %s, days = %s
                        WHERE id = %s
                        """,
                        (state.low_day, state.high_day, state.completed_day, state.days, pair_id),
                    )
                    row.update(vars(state))
            return self.present(row, user, today)

    @staticmethod
    def confirmations(row):
        return Confirmations(row["low_day"], row["high_day"], row["completed_day"], row["days"])

    @classmethod
    def present(cls, row, user, today):
        days, confirmed, friend_confirmed = streak_status(
            cls.confirmations(row), user == row["low_id"], today
        )
        return {
            "id": row["id"],
            "days": days,
            "confirmed": confirmed,
            "friendConfirmed": friend_confirmed,
            "friend": {
                "id": row["friend_id"],
                "name": row["name"],
                "username": row["username"],
                "photoUrl": row["photo_url"],
            },
        }
