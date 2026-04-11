"""Simple rate limiter for LinkedIn API calls."""

from datetime import datetime, date


class RateLimiter:
    """Track daily API calls to stay within LinkedIn's limits.

    LinkedIn allows ~100 API calls per day for personal profiles.
    For 3-5 posts/day this is well within limits.
    """

    def __init__(self, daily_limit: int = 80):
        self.daily_limit = daily_limit
        self._calls: list[datetime] = []
        self._current_date: date | None = None

    def _reset_if_new_day(self):
        today = date.today()
        if self._current_date != today:
            self._calls = []
            self._current_date = today

    def can_post(self) -> bool:
        """Check if we're within daily rate limits."""
        self._reset_if_new_day()
        return len(self._calls) < self.daily_limit

    def record_call(self):
        """Record an API call."""
        self._reset_if_new_day()
        self._calls.append(datetime.utcnow())

    def calls_today(self) -> int:
        """Return how many API calls have been made today."""
        self._reset_if_new_day()
        return len(self._calls)

    def calls_remaining(self) -> int:
        """Return how many API calls are left today."""
        self._reset_if_new_day()
        return max(0, self.daily_limit - len(self._calls))
