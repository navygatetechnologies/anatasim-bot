from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent import run_chat
from llm.factory import get_provider, provider_kind
from mcp_server import mcp
from schemas import ChatRequest, ChatResponse

# mcp.session_manager only exists after streamable_http_app() is called --
# main.py must create mcp_app before the lifespan touches it.
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_provider()  # probe once at startup, not on the first /chat request
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="ANANTASIM chat demo -- mcp_service", lifespan=lifespan)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await run_chat(request)


@app.get("/health")
def health():
    return {"status": "ok", "llm": provider_kind()}


# Mounted at root (not /mcp): mounting at /mcp emits a 307 trailing-slash
# redirect that MCP clients do not follow.
app.mount("/", mcp_app)
