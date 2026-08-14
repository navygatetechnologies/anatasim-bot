import os

from dotenv import load_dotenv

load_dotenv()

# Any OpenAI-compatible server works here (Ollama, LM Studio, OpenAI):
# only the base URL, model name and key change. If it isn't reachable, this
# demo automatically falls back to a small offline scripted brain -- see
# app/llm/factory.py.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")

# The real service talks to two hosts (CONTROLLER_HOST + OF_API_HOST) --
# this demo's `backend/` serves both route sets from one app, so one host
# covers it.
BACKEND_HOST = os.getenv("BACKEND_HOST", "http://localhost:9001")

# Demo-safe defaults instead of the real service's hard RuntimeError on a
# missing key -- there's no real secret to protect here, just a shared
# string this process and `backend/` must agree on.
WORKER_API_KEY = os.getenv("WORKER_API_KEY", "demo-worker-key")
PREPROCESSOR_API_KEY = os.getenv("PREPROCESSOR_API_KEY", "demo-preprocessor-key")

AGENT_MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "10"))
