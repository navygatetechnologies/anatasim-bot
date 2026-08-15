"""LLM provider factory with background health watcher.

Fixes four bugs in the original one-shot implementation:

  Bug 1 — provider cached forever, never re-evaluated.
  Bug 2 — no recovery when real LLM goes down after startup.
  Bug 3 — no upgrade when LLM comes back after being down at startup.
  Bug 4 — TCP probe was synchronous, blocking the async event loop.

Design
------
_ProviderManager holds the current provider and kind as instance state
(not module globals) and exposes a refresh() method that re-probes the
LLM endpoint and switches the provider if the status changed.

start_health_watcher() runs refresh() in a background asyncio task every
LLM_HEALTH_INTERVAL seconds for the lifetime of the service. It logs a
warning on degradation and info on recovery so alerts can be configured.

The probe itself is now async (asyncio.open_connection) so it never
blocks the event loop while waiting for the TCP handshake timeout.
"""
import asyncio
from typing import Literal

import config
from llm.base import LLMProvider
from llm.fake import FakeLLMProvider
from llm.openai_compat import OpenAICompatProvider
from logger import get_logger

log = get_logger(__name__)

ProviderKind = Literal["real", "fake", "unknown"]


async def _real_llm_reachable(base_url: str) -> bool:
    """Async TCP probe -- does NOT block the event loop.

    Opens a connection to the LLM endpoint with a short timeout.
    Returns True if the endpoint accepts the connection, False otherwise.
    Using asyncio.open_connection instead of socket.create_connection
    fixes Bug 4 (synchronous blocking call in async code).
    """
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=0.5,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


class _ProviderManager:
    """Holds the active provider as instance state so it can be swapped
    at runtime without affecting in-flight requests.

    In-flight requests hold a reference to the provider object they started
    with; swapping _provider under them is safe because Python object
    replacement is atomic at the interpreter level.
    """

    def __init__(self) -> None:
        self._provider: LLMProvider | None = None
        self._kind: ProviderKind = "unknown"

    @property
    def kind(self) -> ProviderKind:
        return self._kind

    def get(self) -> LLMProvider:
        """Return the current provider. Initialises synchronously on first
        call using a blocking probe -- this only runs once at startup inside
        the lifespan before the server starts accepting requests, so blocking
        is acceptable here."""
        if self._provider is None:
            import socket
            from urllib.parse import urlparse
            parsed = urlparse(config.LLM_BASE_URL)
            host = parsed.hostname or "localhost"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    reachable = True
            except OSError:
                reachable = False
            self._set(reachable)
            log.info("llm_provider_initialised", kind=self._kind, url=config.LLM_BASE_URL)
        return self._provider  # type: ignore[return-value]

    async def refresh(self) -> None:
        """Re-probe the LLM endpoint and swap the provider if status changed.
        This is the fix for Bugs 1, 2, and 3 -- called periodically by the
        health watcher so the provider is never permanently stale.
        """
        reachable = await _real_llm_reachable(config.LLM_BASE_URL)
        new_kind: ProviderKind = "real" if reachable else "fake"

        if new_kind == self._kind:
            return  # no change, nothing to do

        old_kind = self._kind
        self._set(reachable)

        if old_kind == "real" and new_kind == "fake":
            # Real LLM went down -- WARNING so alerts can fire on this
            log.warning(
                "llm_provider_degraded",
                from_kind=old_kind,
                to_kind=new_kind,
                url=config.LLM_BASE_URL,
            )
        elif old_kind in ("fake", "unknown") and new_kind == "real":
            # LLM came back online -- INFO, good news
            log.info(
                "llm_provider_recovered",
                from_kind=old_kind,
                to_kind=new_kind,
                url=config.LLM_BASE_URL,
            )

    def _set(self, reachable: bool) -> None:
        if reachable:
            self._provider = OpenAICompatProvider(
                config.LLM_BASE_URL, config.LLM_MODEL, config.LLM_API_KEY
            )
            self._kind = "real"
        else:
            self._provider = FakeLLMProvider()
            self._kind = "fake"


# Module-level singleton -- one manager for the process lifetime.
_manager = _ProviderManager()


def get_provider() -> LLMProvider:
    """Return the current active LLM provider.
    Safe to call from any coroutine -- returns the provider the manager
    has decided is active right now."""
    return _manager.get()


def provider_kind() -> ProviderKind:
    """Return 'real', 'fake', or 'unknown'. Read by /health endpoint."""
    return _manager.kind


async def start_health_watcher() -> None:
    """Background task: re-probe the LLM endpoint every LLM_HEALTH_INTERVAL
    seconds and swap the provider if its reachability changed.

    Call this from main.py's lifespan and cancel the returned task on
    shutdown. If LLM_HEALTH_INTERVAL is 0 the watcher is disabled.
    """
    interval = config.LLM_HEALTH_INTERVAL
    if interval <= 0:
        log.info("llm_health_watcher_disabled")
        return

    log.info("llm_health_watcher_started", interval_seconds=interval)
    while True:
        await asyncio.sleep(interval)
        try:
            await _manager.refresh()
        except Exception as exc:
            # Never let a probe error crash the watcher loop
            log.error("llm_health_watcher_error", error=str(exc))
