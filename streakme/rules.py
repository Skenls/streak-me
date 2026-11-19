import base64
import hmac
import re
import secrets
import struct
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

RESTORE_LIMIT = 5
STATIC_INVITE = re.compile(r"[A-Za-z0-9_-]{24}")
CHAT_KEY = re.compile(r"[A-Za-z0-9_-]{38}")
INVITE_TTL = timedelta(days=7)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


@dataclass(frozen=True)
class Confirmations:
    low_day: date | None
    high_day: date | None
    completed_day: date | None
    days: int

    def lost_on(self) -> date | None:
        return self.completed_day + timedelta(days=2) if self.completed_day else None

    def restore(self, today: date) -> "Confirmations":
        if (lost_on := self.lost_on()) is None or lost_on > today:
            return self
        return replace(self, completed_day=today - timedelta(days=1))

    def confirm(self, is_low: bool, today: date) -> "Confirmations":
        if self.completed_day == today or ((lost_on := self.lost_on()) and lost_on <= today):
            return self
        state = (
            replace(self, low_day=today) if is_low else replace(self, high_day=today)
        )
        if state.low_day == state.high_day == today:
            days = self.days + 1 if self.completed_day == today - timedelta(days=1) else 1
            return replace(state, completed_day=today, days=days)
        return state


def streak_status(state: Confirmations, is_low: bool, today: date) -> tuple[int, bool, bool, str]:
    low, high = state.low_day == today, state.high_day == today
    lost_on = state.lost_on()
    status = "lost" if lost_on and lost_on <= today else "frozen"
    if state.completed_day == today:
        status = "active"
    confirmed, friend = (low, high) if is_low else (high, low)
    return state.days, confirmed, friend, status


def restores_left(month: date | None, used: int, today: date) -> int:
    return RESTORE_LIMIT - used if month == today.replace(day=1) else RESTORE_LIMIT


def chat_mac(payload: bytes, secret: str) -> bytes:
    return hmac.digest(secret.encode(), b"streakme:private-chat:" + payload, "sha256")[:12]


def issue_chat_key(user_id: int, secret: str) -> str:
    payload = struct.pack(">Q8s", user_id, secrets.token_bytes(8))
    return base64.urlsafe_b64encode(payload + chat_mac(payload, secret)).decode().rstrip("=")


def read_chat_key(key: str, secret: str) -> int | None:
    if not CHAT_KEY.fullmatch(key):
        return None
    raw = base64.urlsafe_b64decode(key + "==")
    payload, mac = raw[:-12], raw[-12:]
    if not hmac.compare_digest(mac, chat_mac(payload, secret)):
        return None
    return struct.unpack(">Q8s", payload)[0]


def invite_mac(payload: bytes, secret: str) -> bytes:
    return hmac.digest(secret.encode(), b"streakme:invite:" + payload, "sha256")[:12]


def issue_invite(user_id: int, secret: str, now: datetime | None = None) -> str:
    expires = int(((now or datetime.now(UTC)) + INVITE_TTL).timestamp())
    payload = struct.pack(">QI8s", user_id, expires, secrets.token_bytes(8))
    return base64.urlsafe_b64encode(payload + invite_mac(payload, secret)).decode().rstrip("=")


def read_invite(token: str, secret: str, now: datetime | None = None) -> int | None:
    if not TOKEN_PATTERN.fullmatch(token):
        return None
    raw = base64.urlsafe_b64decode(token + "=")
    if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
        return None
    payload, mac = raw[:-12], raw[-12:]
    if not hmac.compare_digest(mac, invite_mac(payload, secret)):
        return None
    inviter, expires, _ = struct.unpack(">QI8s", payload)
    return inviter if (now or datetime.now(UTC)).timestamp() < expires else None
