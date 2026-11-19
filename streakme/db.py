import secrets
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .rules import RESTORE_LIMIT, Confirmations, restores_left, streak_status

PAIR_VIEW = """
    SELECT s.*, p.id AS friend_id, p.name, p.username, p.photo_url
    FROM streaks s JOIN profiles p ON p.id =
        CASE WHEN s.low_id = %(user)s THEN s.high_id ELSE s.low_id END
    WHERE %(user)s IN (s.low_id, s.high_id)
"""


# A streak is removed if its quota was exhausted in the month in which it was lost,
# even if the worker was offline until the following month.
EXHAUSTED = """
    s.restore_count = %(limit)s
    AND s.completed_day + 2 <= %(today)s
    AND s.restore_month = date_trunc('month', (s.completed_day + 2)::timestamp)::date
"""
VISIBLE_PAIRS = PAIR_VIEW + " AND NOT COALESCE((" + EXHAUSTED + "), false)"


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

    async def invite_code(self, user: int, *, reset: bool = False) -> str:
        generated = secrets.token_urlsafe(18)
        async with self.pool.connection() as conn:
            if not reset:
                existing = await conn.execute("SELECT invite_code FROM profiles WHERE id = %s", (user,))
                if code := (await existing.fetchone())["invite_code"]:
                    return code
            if reset:
                result = await conn.execute(
                    """
                    UPDATE profiles SET invite_code = %s, legacy_invites_revoked = true
                    WHERE id = %s RETURNING invite_code
                    """,
                    (generated, user),
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE profiles SET invite_code = COALESCE(invite_code, %s)
                    WHERE id = %s RETURNING invite_code
                    """,
                    (generated, user),
                )
            return (await result.fetchone())["invite_code"]

    async def accept_invite(self, code: str, receiver: int, *, legacy_inviter: int | None = None):
        async with self.pool.connection() as conn:
            if legacy_inviter is None:
                result = await conn.execute(
                    "SELECT id FROM profiles WHERE invite_code = %s FOR SHARE", (code,)
                )
            else:
                result = await conn.execute(
                    """
                    SELECT id FROM profiles WHERE id = %s AND NOT legacy_invites_revoked FOR SHARE
                    """,
                    (legacy_inviter,),
                )
            owner = await result.fetchone()
            if owner is None:
                return "invalid"
            inviter = owner["id"]
            if inviter == receiver:
                return "own"
            if legacy_inviter is not None:
                claim = await conn.execute(
                    """
                    INSERT INTO claimed_invites (token, receiver_id) VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (code, receiver),
                )
                if claim.rowcount == 0:
                    return "claimed"
            low, high = sorted((inviter, receiver))
            await conn.execute(
                "DELETE FROM streaks s WHERE low_id = %(low)s AND high_id = %(high)s AND " + EXHAUSTED,
                {"low": low, "high": high, "today": datetime.now(UTC).date(), "limit": RESTORE_LIMIT},
            )
            await conn.execute(
                """
                INSERT INTO streaks (low_id, high_id) VALUES (%s, %s)
                ON CONFLICT (low_id, high_id) DO NOTHING
                """,
                (low, high),
            )
            return "ok"

    async def list(self, user: int):
        today = datetime.now(UTC).date()
        async with self.pool.connection() as conn:
            rows = await conn.execute(
                VISIBLE_PAIRS + " ORDER BY s.id DESC",
                {"user": user, "today": today, "limit": RESTORE_LIMIT},
            )
            return [self.present(row, user, today) for row in await rows.fetchall()]

    async def get(self, pair_id: int, user: int, *, action: Literal["confirm", "restore"] | None = None):
        today = datetime.now(UTC).date()
        async with self.pool.connection() as conn:
            query = VISIBLE_PAIRS + " AND s.id = %(pair)s"
            if action:
                query += " FOR UPDATE OF s"
            result = await conn.execute(
                query, {"user": user, "pair": pair_id, "today": today, "limit": RESTORE_LIMIT}
            )
            row = await result.fetchone()
            if row is None:
                return None
            previous = self.confirmations(row)
            if action == "confirm":
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
            elif action == "restore":
                updated = previous.restore(today)
                remaining = restores_left(row["restore_month"], row["restore_count"], today)
                if updated != previous and remaining:
                    month, count = today.replace(day=1), RESTORE_LIMIT - remaining + 1
                    await conn.execute(
                        """
                        UPDATE streaks SET completed_day = %s, restore_month = %s, restore_count = %s
                        WHERE id = %s
                        """,
                        (updated.completed_day, month, count, pair_id),
                    )
                    row.update(completed_day=updated.completed_day, restore_month=month, restore_count=count)
            return self.present(row, user, today)

    async def delete(self, pair_id: int, user: int) -> bool:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM streaks WHERE id = %s AND %s IN (low_id, high_id)", (pair_id, user)
            )
            return bool(result.rowcount)

    async def inline_pair(self, chat: str, owner: int, user: int) -> int | None:
        async with self.pool.connection() as conn:
            if owner != user:
                low, high = sorted((owner, user))
                await conn.execute(
                    """
                    INSERT INTO inline_pairs (chat_instance, streak_id)
                    SELECT %s, s.id FROM streaks s WHERE low_id = %s AND high_id = %s FOR KEY SHARE
                    ON CONFLICT DO NOTHING
                    """,
                    (chat, low, high),
                )
            result = await conn.execute(
                """
                SELECT s.id FROM inline_pairs i JOIN streaks s ON i.streak_id = s.id
                WHERE i.chat_instance = %s AND %s IN (s.low_id, s.high_id)
                    AND %s IN (s.low_id, s.high_id)
                """,
                (chat, owner, user),
            )
            row = await result.fetchone()
            return row["id"] if row else None

    async def expire(self, today):
        async with self.pool.connection() as conn:
            await conn.execute("DELETE FROM streaks s WHERE " + EXHAUSTED, {"today": today, "limit": RESTORE_LIMIT})
            await conn.execute("DELETE FROM streak_reminders WHERE day < %s::date - 2", (today,))
            await conn.execute("DELETE FROM claimed_invites WHERE claimed_at < now() - interval '7 days'")

    async def claim_reminders(self, today):
        async with self.pool.connection() as conn:
            rows = await conn.execute(
                """
                WITH waiting AS (
                    SELECT p.id, count(*) AS total
                    FROM streaks s CROSS JOIN LATERAL (
                        VALUES (s.low_id, s.low_day), (s.high_id, s.high_day)
                    ) AS p(id, marked)
                    WHERE s.completed_day = %(day)s::date - 1
                        AND p.marked IS DISTINCT FROM %(day)s
                        AND NOT EXISTS (
                            SELECT 1 FROM streak_reminders r WHERE r.day = %(day)s AND r.user_id = p.id
                        )
                    GROUP BY p.id ORDER BY p.id LIMIT 25
                ), sent AS (
                    INSERT INTO streak_reminders (day, user_id)
                    SELECT %(day)s, id FROM waiting ON CONFLICT DO NOTHING RETURNING user_id
                )
                SELECT id, total FROM waiting JOIN sent ON waiting.id = sent.user_id
                """,
                {"day": today},
            )
            return await rows.fetchall()

    async def release_reminders(self, day, users):
        async with self.pool.connection() as conn:
            await conn.execute(
                "DELETE FROM streak_reminders WHERE day = %s AND user_id = ANY(%s)", (day, users)
            )

    @staticmethod
    def confirmations(row):
        return Confirmations(row["low_day"], row["high_day"], row["completed_day"], row["days"])

    @classmethod
    def present(cls, row, user, today):
        days, confirmed, friend_confirmed, status = streak_status(
            cls.confirmations(row), user == row["low_id"], today
        )
        return {
            "id": row["id"],
            "days": days,
            "status": status,
            "restoresLeft": restores_left(row["restore_month"], row["restore_count"], today),
            "confirmed": confirmed,
            "friendConfirmed": friend_confirmed,
            "friend": {
                "id": row["friend_id"],
                "name": row["name"],
                "username": row["username"],
                "photoUrl": telegram_photo(row["photo_url"]),
            },
        }
