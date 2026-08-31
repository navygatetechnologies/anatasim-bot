"""Per-user sliding window rate limiter.

Two independent limits are enforced per user_id:
  - RPM (requests per minute): protects against burst abuse and runaway
    frontends. Default: 20.
  - RPD (requests per day): protects against LLM cost exhaustion by a
    single user over a full day. Default: 200.

Sliding window means the window moves continuously with time -- not a
fixed "bucket resets at :00 every minute". This is fairer (no burst at
the window boundary) and harder to game.

How the sliding window works
-----------------------------
Every request timestamp is appended to a deque for that user. Before
checking the count, all timestamps older than the window size are dropped
from the front of the deque. The remaining length is the number of
requests in the current window. If it equals or exceeds the limit, the
request is rejected.

Thread / async safety
---------------------
All state is in a plain dict of deques. asyncio is single-threaded so
concurrent coroutines never truly run simultaneously -- no lock needed.
For multi-process deployments (multiple uvicorn workers) each process has
its own counter; a shared Redis store would be needed at that scale.

Confirm-only requests are exempt
---------------------------------
When a user confirms a PendingAction there is no LLM call, no agent loop,
and no backend write beyond the single tool execution. Blocking confirms
would strand users mid-conversation with no way to proceed or cancel.
The caller passes is_confirm=True to skip the check entirely.
"""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class _UserBucket:
    minute: Deque[float] = field(default_factory=deque)
    day:    Deque[float] = field(default_factory=deque)


class RateLimitExceeded(Exception):
    """Raised when a user has exceeded a rate limit window.

    Attributes:
        window   -- "minute" or "day"
        limit    -- the configured limit that was hit
        retry_after -- approximate seconds until the oldest request
                       falls outside the window (i.e. when to retry)
    """
    def __init__(self, window: str, limit: int, retry_after: float):
        self.window = window
        self.limit = limit
        self.retry_after = round(retry_after)
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window}. "
            f"Retry after {self.retry_after}s."
        )


class RateLimiter:
    """Sliding window rate limiter keyed by user_id.

    Usage:
        limiter = RateLimiter(rpm=20, rpd=200)
        try:
            limiter.check(user_id, is_confirm=False)
        except RateLimitExceeded as exc:
            # return 429 to caller
    """

    _MINUTE = 60.0
    _DAY    = 86_400.0

    def __init__(self, rpm: int = 20, rpd: int = 200):
        self._rpm = rpm
        self._rpd = rpd
        self._buckets: dict[str, _UserBucket] = {}

    def check(self, user_id: str, is_confirm: bool = False) -> None:
        """Record this request and raise RateLimitExceeded if over limit.

        Confirm-only requests bypass both limits -- see module docstring.
        Set rpm=0 or rpd=0 in config to disable that specific limit.
        """
        if is_confirm:
            return

        now = time.monotonic()
        bucket = self._buckets.setdefault(user_id, _UserBucket())

        # --- per-minute check ---
        if self._rpm > 0:
            self._evict(bucket.minute, now, self._MINUTE)
            if len(bucket.minute) >= self._rpm:
                oldest = bucket.minute[0]
                retry_after = self._MINUTE - (now - oldest)
                raise RateLimitExceeded("minute", self._rpm, retry_after)

        # --- per-day check ---
        if self._rpd > 0:
            self._evict(bucket.day, now, self._DAY)
            if len(bucket.day) >= self._rpd:
                oldest = bucket.day[0]
                retry_after = self._DAY - (now - oldest)
                raise RateLimitExceeded("day", self._rpd, retry_after)

        # Both checks passed -- record the timestamp in both windows
        bucket.minute.append(now)
        bucket.day.append(now)

    def current_counts(self, user_id: str) -> dict:
        """Return current request counts for a user -- useful for logging."""
        now = time.monotonic()
        bucket = self._buckets.get(user_id)
        if bucket is None:
            return {"rpm": 0, "rpd": 0}
        self._evict(bucket.minute, now, self._MINUTE)
        self._evict(bucket.day, now, self._DAY)
        return {"rpm": len(bucket.minute), "rpd": len(bucket.day)}

    @staticmethod
    def _evict(window: Deque[float], now: float, size: float) -> None:
        """Drop timestamps older than `size` seconds from the left."""
        cutoff = now - size
        while window and window[0] <= cutoff:
            window.popleft()
