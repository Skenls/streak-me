import asyncio
import secrets
from contextlib import contextmanager


class DashboardUpdates:
    """Keep only the active subscribers and one bit of pending work per socket."""

    def __init__(self):
        self.listeners: dict[int, set[asyncio.Event]] = {}
        self.generation = secrets.token_hex(6)
        self.revision = 0

    @property
    def snapshot(self) -> str:
        return f"{self.generation}:{self.revision}"

    @contextmanager
    def watch(self, user: int):
        listeners = self.listeners.setdefault(user, set())
        if len(listeners) >= 3:
            yield None
            return
        pending = asyncio.Event()
        listeners.add(pending)
        try:
            yield pending
        finally:
            listeners.remove(pending)
            if not listeners:
                del self.listeners[user]

    def changed(self, *users: int):
        self.revision += 1
        for user in users:
            for signal in self.listeners.get(user, ()):
                signal.set()

    def day_changed(self):
        self.changed(*self.listeners)
