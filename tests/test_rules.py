import unittest
from datetime import UTC, date, datetime, timedelta

from streakme.rules import Confirmations, issue_invite, read_invite, streak_status


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 19)
        self.yesterday = self.today - timedelta(days=1)

    def test_each_friend_must_confirm_and_only_once(self):
        state = Confirmations(self.yesterday, self.yesterday, self.yesterday, 8)
        first = state.confirm(True, self.today)
        self.assertEqual(streak_status(first, True, self.today), (8, True, False))
        self.assertEqual(first.confirm(True, self.today), first)
        finished = first.confirm(False, self.today)
        self.assertEqual(streak_status(finished, True, self.today), (9, True, True))
        self.assertEqual(finished.confirm(False, self.today), finished)

    def test_missed_day_resets_visible_counter_and_restarts_at_one(self):
        state = Confirmations(self.yesterday, None, self.yesterday, 8)
        tomorrow = self.today + timedelta(days=1)
        self.assertEqual(streak_status(state, False, tomorrow), (0, False, False))
        self.assertEqual(state.confirm(False, tomorrow).confirm(True, tomorrow).days, 1)

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
