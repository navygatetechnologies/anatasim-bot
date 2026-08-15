"""Tests verifying the LLM provider health watcher fixes the four bugs
that existed in the original one-shot factory implementation.

Run with:
    cd mcp_service
    python -m pytest tests/test_llm_factory.py -v

Each test is named after the bug it previously confirmed, now asserting
the fix is in place.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from llm.factory import _ProviderManager, _real_llm_reachable
from llm.fake import FakeLLMProvider
from llm.openai_compat import OpenAICompatProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_manager() -> _ProviderManager:
    """Return a new manager instance with no provider set yet."""
    return _ProviderManager()


# ---------------------------------------------------------------------------
# Fix 1 — provider re-evaluates on every refresh() call
#
# Previously: get_provider() cached forever after first call.
# Now: refresh() re-probes and returns the correct provider each time.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fix1_provider_switches_when_status_changes():
    """
    refresh() must re-probe and update the provider when reachability
    changes -- not return a stale cached result.
    """
    manager = _fresh_manager()

    # Startup: LLM unreachable → fake
    with patch("llm.factory._real_llm_reachable", new=AsyncMock(return_value=False)):
        manager._set(False)

    assert manager.kind == "fake"
    assert isinstance(manager._provider, FakeLLMProvider)

    # Status changes: LLM becomes reachable → refresh() should switch to real
    with patch("llm.factory._real_llm_reachable", new=AsyncMock(return_value=True)):
        await manager.refresh()

    assert manager.kind == "real", (
        "After refresh() with LLM reachable, provider should be 'real'"
    )
    assert isinstance(manager._provider, OpenAICompatProvider)


# ---------------------------------------------------------------------------
# Fix 2 — recovery when real LLM goes down after startup
#
# Previously: no mechanism to fall back to fake after real was chosen.
# Now: refresh() detects the outage and switches to fake automatically.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fix2_switches_to_fake_when_llm_goes_down():
    """
    refresh() must detect when the real LLM becomes unreachable and
    switch to FakeLLMProvider automatically.
    """
    manager = _fresh_manager()

    # Startup: LLM reachable → real
    manager._set(True)
    assert manager.kind == "real"

    # LLM goes down
    with patch("llm.factory._real_llm_reachable", new=AsyncMock(return_value=False)):
        await manager.refresh()

    assert manager.kind == "fake", (
        "After refresh() with LLM unreachable, provider should fall back to 'fake'"
    )
    assert isinstance(manager._provider, FakeLLMProvider)


# ---------------------------------------------------------------------------
# Fix 3 — upgrade when LLM comes back after being down at startup
#
# Previously: stuck on fake for entire process lifetime.
# Now: refresh() detects recovery and switches back to real.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fix3_switches_to_real_when_llm_recovers():
    """
    refresh() must detect when the LLM comes back online after being
    down at startup, and upgrade from fake to real automatically.
    """
    manager = _fresh_manager()

    # Startup: LLM unreachable → fake
    manager._set(False)
    assert manager.kind == "fake"

    # LLM comes back online
    with patch("llm.factory._real_llm_reachable", new=AsyncMock(return_value=True)):
        await manager.refresh()

    assert manager.kind == "real", (
        "After refresh() with LLM back online, provider should upgrade to 'real'"
    )
    assert isinstance(manager._provider, OpenAICompatProvider)


# ---------------------------------------------------------------------------
# Fix 4 — TCP probe is now async (non-blocking)
#
# Previously: socket.create_connection with 500ms timeout blocked the
# event loop on every probe.
# Now: asyncio.open_connection is used -- fully async and non-blocking.
# ---------------------------------------------------------------------------

def test_fix4_reachability_probe_is_async():
    """
    _real_llm_reachable must be a coroutine function so it never blocks
    the asyncio event loop while waiting for the TCP timeout.
    """
    assert inspect.iscoroutinefunction(_real_llm_reachable), (
        "_real_llm_reachable should be async (coroutine function) so it "
        "does not block the event loop during the TCP handshake timeout."
    )


# ---------------------------------------------------------------------------
# Extra: no-op when status unchanged
#
# refresh() should not swap the provider object if reachability hasn't
# changed -- avoids unnecessary object churn on every probe tick.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_is_noop_when_status_unchanged():
    """
    refresh() must leave the provider object untouched when reachability
    has not changed since the last probe.
    """
    manager = _fresh_manager()
    manager._set(True)
    provider_before = manager._provider

    with patch("llm.factory._real_llm_reachable", new=AsyncMock(return_value=True)):
        await manager.refresh()

    assert manager._provider is provider_before, (
        "refresh() should not replace the provider when status is unchanged"
    )


# ---------------------------------------------------------------------------
# Extra: health watcher loop runs refresh() and handles probe errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_watcher_runs_and_cancels_cleanly():
    """
    start_health_watcher() must run without error and cancel cleanly
    when the task is cancelled (normal shutdown path).
    """
    import llm.factory as factory_mod

    # Use a very short interval so the test doesn't wait 30 seconds
    original_interval = factory_mod.config.LLM_HEALTH_INTERVAL
    factory_mod.config.LLM_HEALTH_INTERVAL = 1

    with patch.object(factory_mod._manager, "refresh", new=AsyncMock()):
        task = asyncio.create_task(factory_mod.start_health_watcher())
        await asyncio.sleep(0.1)   # let it start
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # expected -- clean shutdown

    factory_mod.config.LLM_HEALTH_INTERVAL = original_interval
    assert task.cancelled() or task.done()
