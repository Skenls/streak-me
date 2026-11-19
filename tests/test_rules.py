import unittest
from datetime import UTC, date, datetime, timedelta

from streakme.rules import Confirmations, issue_chat_key, issue_invite, read_chat_key, read_invite, restores_left, streak_status


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 19)
        self.yesterday = self.today - timedelta(days=1)

    def test_each_friend_must_confirm_and_only_once(self):
        state = Confirmations(self.yesterday, self.yesterday, self.yesterday, 8)
        first = state.confirm(True, self.today)
        self.assertEqual(streak_status(first, True, self.today), (8, True, False, "frozen"))
        self.assertEqual(first.confirm(True, self.today), first)
        finished = first.confirm(False, self.today)
        self.assertEqual(streak_status(finished, True, self.today), (9, True, True, "active"))
        self.assertEqual(finished.confirm(False, self.today), finished)

    def test_missed_day_freezes_progress_until_restored(self):
        state = Confirmations(self.yesterday, None, self.yesterday, 8)
        tomorrow = self.today + timedelta(days=1)
        self.assertEqual(streak_status(state, False, tomorrow), (8, False, False, "lost"))
        self.assertEqual(state.confirm(False, tomorrow), state)
        restored = state.restore(tomorrow)
        self.assertEqual(streak_status(restored, False, tomorrow), (8, False, False, "frozen"))
        self.assertEqual(restored.confirm(False, tomorrow).confirm(True, tomorrow).days, 9)

    def test_monthly_quota_and_chat_signature(self):
        self.assertEqual(restores_left(self.today.replace(day=1), 5, self.today), 0)
        self.assertEqual(restores_left(self.today.replace(month=10, day=1), 5, self.today), 5)
        key = issue_chat_key(123, "secret")
        self.assertLessEqual(len("chat:confirm:" + key), 64)
        self.assertEqual(read_chat_key(key, "secret"), 123)
        self.assertIsNone(read_chat_key(key, "wrong"))

    def test_invite_authenticity_length_and_expiry(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        token = issue_invite(123, "secret", now)
        self.assertLessEqual(len("join_" + token), 64)
        self.assertEqual(read_invite(token, "secret", now), 123)
        self.assertIsNone(read_invite(token, "another", now))
        self.assertIsNone(read_invite(token, "secret", now + timedelta(days=7)))
        self.assertIsNone(read_invite("invalid+encoding", "secret", now))


if __name__ == "__main__":
    unittest.main()
