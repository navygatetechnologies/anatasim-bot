import socket
from urllib.parse import urlparse

import config
from llm.base import LLMProvider
from llm.fake import FakeLLMProvider
from llm.openai_compat import OpenAICompatProvider

_provider: LLMProvider | None = None
_provider_kind: str | None = None  # "real" or "fake" -- read by main.py's /health for the CLI banner


def _real_llm_reachable(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def get_provider() -> LLMProvider:
    """Ollama, LM Studio and OpenAI all speak the OpenAI API, so one real
    provider covers them via LLM_BASE_URL/LLM_MODEL/LLM_API_KEY -- same as
    the real service. Unlike the real service, this demo probes that
    endpoint once (cached for the life of the process) and falls back to a
    small offline scripted brain (llm/fake.py) when nothing is reachable, so
    the folder runs with zero external setup."""
    global _provider, _provider_kind
    if _provider is None:
        if _real_llm_reachable(config.LLM_BASE_URL):
            _provider = OpenAICompatProvider(config.LLM_BASE_URL, config.LLM_MODEL, config.LLM_API_KEY)
            _provider_kind = "real"
        else:
            _provider = FakeLLMProvider()
            _provider_kind = "fake"
    return _provider


def provider_kind() -> str:
    """"real" or "fake" once get_provider() has run at least once, else
    "unknown"."""
    return _provider_kind or "unknown"
