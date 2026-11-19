from datetime import UTC, datetime
from urllib.parse import urlsplit

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .rules import Confirmations, streak_status

PAIR_VIEW = """
    SELECT s.*, p.id AS friend_id, p.name, p.username, p.photo_url
    FROM streaks s JOIN profiles p ON p.id =
        CASE WHEN s.low_id = %(user)s THEN s.high_id ELSE s.low_id END
    WHERE %(user)s IN (s.low_id, s.high_id)
"""


def telegram_photo(value: str | None) -> str | None:
    if not value:
        return None
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            return None
    except ValueError:
        return None
    host = url.hostname or ""
    if host in {"t.me", "telegram-cdn.org"} or host.endswith((".telegram-cdn.org", ".telesco.pe")):
        return value
    return None


class Database:
    def __init__(self, dsn: str):
        self.pool = AsyncConnectionPool(
            dsn, open=False, min_size=1, max_size=8, max_waiting=24, timeout=2,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": 5,
                "options": "-c statement_timeout=4000 -c idle_in_transaction_session_timeout=5000",
            },
        )

    async def close(self):
        await self.pool.close()

    async def open(self):
        await self.pool.open(wait=True, timeout=10)

    async def check(self):
        async with self.pool.connection() as conn:
            await conn.execute("SELECT 1")

    async def save_profile(self, user):
        name = " ".join(part for part in (user.first_name, user.last_name) if part)
        has_photo = hasattr(user, "photo_url")
        photo = telegram_photo(getattr(user, "photo_url", None))
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO profiles (id, name, username, photo_url) VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, username = EXCLUDED.username,
                    photo_url = CASE WHEN %s THEN EXCLUDED.photo_url ELSE profiles.photo_url END
                WHERE (profiles.name, profiles.username) IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.username)
                    OR (%s AND profiles.photo_url IS DISTINCT FROM EXCLUDED.photo_url)
                """,
                (user.id, name, user.username, photo, has_photo, has_photo),
            )

    async def accept(self, token: str, inviter: int, receiver: int) -> bool:
        low, high = sorted((inviter, receiver))
        async with self.pool.connection() as conn:
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
        async with self.pool.connection() as conn:
            rows = await conn.execute(PAIR_VIEW + " ORDER BY s.id DESC", {"user": user})
            today = datetime.now(UTC).date()
            return [self.present(row, user, today) for row in await rows.fetchall()]

    async def get(self, pair_id: int, user: int, *, confirm: bool = False):
        async with self.pool.connection() as conn:
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
                "photoUrl": telegram_photo(row["photo_url"]),
            },
        }
