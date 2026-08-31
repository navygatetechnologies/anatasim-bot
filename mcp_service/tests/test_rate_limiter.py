"""Tests for the sliding window rate limiter.

Run with:
    cd mcp_service
    python -m pytest tests/test_rate_limiter.py -v

Covers:
  - RPM limit blocks at the right threshold
  - RPD limit blocks at the right threshold
  - Sliding window evicts old timestamps correctly
  - Confirm requests are exempt from both limits
  - Disabled limits (0) never block
  - Different users have independent counters
  - retry_after is positive and reasonable
  - current_counts reflects real state
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
from unittest.mock import patch

import pytest

from rate_limiter import RateLimiter, RateLimitExceeded


# ---------------------------------------------------------------------------
# RPM limit
# ---------------------------------------------------------------------------

def test_rpm_blocks_at_limit():
    """Exactly at the RPM limit the next request should be rejected."""
    limiter = RateLimiter(rpm=3, rpd=0)  # rpd=0 disables daily limit

    # First 3 requests pass
    for _ in range(3):
        limiter.check("user-a")

    # 4th request hits the limit
    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.check("user-a")

    assert exc_info.value.window == "minute"
    assert exc_info.value.limit == 3


def test_rpm_allows_exactly_at_limit():
    """Requests up to but not exceeding the limit must all pass."""
    limiter = RateLimiter(rpm=5, rpd=0)

    for i in range(5):
        limiter.check("user-b")   # should not raise


def test_rpm_resets_after_window():
    """After the minute window passes, the counter resets and requests
    are allowed again."""
    limiter = RateLimiter(rpm=2, rpd=0)

    # Use up the limit
    limiter.check("user-c")
    limiter.check("user-c")

    # Simulate 61 seconds passing — timestamps fall outside the window
    now = time.monotonic()
    with patch("time.monotonic", return_value=now + 61):
        # Should pass — old timestamps evicted
        limiter.check("user-c")


# ---------------------------------------------------------------------------
# RPD limit
# ---------------------------------------------------------------------------

def test_rpd_blocks_at_limit():
    """Exactly at the RPD limit the next request should be rejected."""
    limiter = RateLimiter(rpm=0, rpd=5)  # rpm=0 disables per-minute limit

    for _ in range(5):
        limiter.check("user-d")

    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.check("user-d")

    assert exc_info.value.window == "day"
    assert exc_info.value.limit == 5


def test_rpd_resets_after_window():
    """After the day window passes, the daily counter resets."""
    limiter = RateLimiter(rpm=0, rpd=2)

    limiter.check("user-e")
    limiter.check("user-e")

    now = time.monotonic()
    with patch("time.monotonic", return_value=now + 86_401):
        limiter.check("user-e")  # should not raise


# ---------------------------------------------------------------------------
# Confirm requests are exempt
# ---------------------------------------------------------------------------

def test_confirm_exempt_from_rpm():
    """Confirm requests must never be blocked even after RPM limit hit."""
    limiter = RateLimiter(rpm=2, rpd=0)

    limiter.check("user-f")
    limiter.check("user-f")

    # Normal request is blocked
    with pytest.raises(RateLimitExceeded):
        limiter.check("user-f", is_confirm=False)

    # Confirm request passes through regardless
    limiter.check("user-f", is_confirm=True)  # must not raise


def test_confirm_exempt_from_rpd():
    """Confirm requests must never be blocked even after RPD limit hit."""
    limiter = RateLimiter(rpm=0, rpd=2)

    limiter.check("user-g")
    limiter.check("user-g")

    with pytest.raises(RateLimitExceeded):
        limiter.check("user-g", is_confirm=False)

    limiter.check("user-g", is_confirm=True)  # must not raise


def test_confirm_does_not_consume_quota():
    """Confirm requests must not count against the user's quota."""
    limiter = RateLimiter(rpm=2, rpd=0)

    # Send 10 confirms — should not consume quota
    for _ in range(10):
        limiter.check("user-h", is_confirm=True)

    # 2 normal requests should still be allowed
    limiter.check("user-h", is_confirm=False)
    limiter.check("user-h", is_confirm=False)

    # 3rd normal request hits the limit
    with pytest.raises(RateLimitExceeded):
        limiter.check("user-h", is_confirm=False)


# ---------------------------------------------------------------------------
# Disabled limits
# ---------------------------------------------------------------------------

def test_rpm_disabled_never_blocks():
    """rpm=0 means no per-minute limit — any number of requests pass."""
    limiter = RateLimiter(rpm=0, rpd=0)

    for _ in range(1000):
        limiter.check("user-i")  # must not raise


def test_rpd_disabled_never_blocks():
    """rpd=0 means no per-day limit — any number of requests pass."""
    limiter = RateLimiter(rpm=0, rpd=0)

    for _ in range(1000):
        limiter.check("user-j")  # must not raise


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------

def test_different_users_have_independent_counters():
    """One user hitting the limit must not affect another user."""
    limiter = RateLimiter(rpm=2, rpd=0)

    # user-k hits the limit
    limiter.check("user-k")
    limiter.check("user-k")

    with pytest.raises(RateLimitExceeded):
        limiter.check("user-k")

    # user-l is completely unaffected
    limiter.check("user-l")  # must not raise
    limiter.check("user-l")  # must not raise


# ---------------------------------------------------------------------------
# retry_after
# ---------------------------------------------------------------------------

def test_retry_after_is_positive():
    """retry_after on a rejected request must be a positive number."""
    limiter = RateLimiter(rpm=1, rpd=0)
    limiter.check("user-m")

    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.check("user-m")

    assert exc_info.value.retry_after > 0


def test_retry_after_does_not_exceed_window():
    """retry_after for RPM must be at most 60 seconds."""
    limiter = RateLimiter(rpm=1, rpd=0)
    limiter.check("user-n")

    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.check("user-n")

    assert exc_info.value.retry_after <= 60


# ---------------------------------------------------------------------------
# current_counts
# ---------------------------------------------------------------------------

def test_current_counts_reflects_usage():
    """current_counts must return accurate rpm and rpd values."""
    limiter = RateLimiter(rpm=10, rpd=100)

    for _ in range(3):
        limiter.check("user-o")

    counts = limiter.current_counts("user-o")
    assert counts["rpm"] == 3
    assert counts["rpd"] == 3


def test_current_counts_unknown_user_returns_zero():
    """current_counts for a user that has never sent a request returns 0."""
    limiter = RateLimiter(rpm=10, rpd=100)
    counts = limiter.current_counts("user-never-seen")
    assert counts["rpm"] == 0
    assert counts["rpd"] == 0


def test_current_counts_after_eviction():
    """current_counts must not include expired timestamps."""
    limiter = RateLimiter(rpm=10, rpd=100)

    limiter.check("user-p")
    limiter.check("user-p")

    now = time.monotonic()
    with patch("time.monotonic", return_value=now + 61):
        counts = limiter.current_counts("user-p")

    assert counts["rpm"] == 0   # minute window expired
    assert counts["rpd"] == 2   # day window still active
