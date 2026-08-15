import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

import config
from agent import run_chat
from llm.factory import get_provider, provider_kind, start_health_watcher
from logger import configure, get_logger, new_request_id
from mcp_server import mcp
from schemas import ChatRequest, ChatResponse

# Configure logging before anything else runs
configure(config.LOG_LEVEL)
log = get_logger(__name__)

# mcp.session_manager only exists after streamable_http_app() is called --
# main.py must create mcp_app before the lifespan touches it.
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise provider synchronously at startup (blocking probe runs once
    # before the server accepts any requests -- acceptable here).
    get_provider()
    log.info("service_started", llm=provider_kind())

    # Start background health watcher -- re-probes LLM every
    # LLM_HEALTH_INTERVAL seconds and swaps provider if status changes.
    watcher = asyncio.create_task(start_health_watcher())

    async with mcp.session_manager.run():
        yield

    # Clean shutdown: cancel the watcher and wait for it to finish
    watcher.cancel()
    try:
        await watcher
    except asyncio.CancelledError:
        pass
    log.info("service_stopped")


app = FastAPI(title="ANANTASIM chat demo -- mcp_service", lifespan=lifespan)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    rid = new_request_id()  # bind a fresh request_id to this async context

    log.info(
        "chat_request_received",
        user_id=request.user_id,
        project_id=request.project_id,
        sim_id=request.sim_id,
        is_confirm=request.confirm is not None,
        history_turns=len(request.history),
    )

    start = time.monotonic()
    response = await run_chat(request)
    duration_ms = round((time.monotonic() - start) * 1000)

    log.info(
        "chat_request_completed",
        user_id=request.user_id,
        project_id=request.project_id,
        sim_id=request.sim_id,
        applied=response.applied,
        has_pending_action=response.pending_action is not None,
        duration_ms=duration_ms,
    )

    return response


@app.get("/health")
def health():
    return {"status": "ok", "llm": provider_kind()}


# Mounted at root (not /mcp): mounting at /mcp emits a 307 trailing-slash
# redirect that MCP clients do not follow.
app.mount("/", mcp_app)
