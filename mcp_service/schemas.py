from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PendingAction(BaseModel):
    """A mutating tool call the model wants to make, staged for a real user
    confirmation instead of executed on the spot -- see agent.py."""
    tool: str
    arguments: Dict[str, Any]
    summary: str


class ChatRequest(BaseModel):
    project_id: str
    sim_id: str
    user_id: str
    message: str
    history: List[ChatMessage] = []
    # Set only when the caller is relaying a user's Confirm click on a
    # previously returned PendingAction -- when present, run_chat executes
    # it directly and skips the LLM entirely (see agent.py).
    confirm: Optional[PendingAction] = None


class ChatResponse(BaseModel):
    message: str
    applied: bool = False
    detail: Optional[Dict[str, Any]] = None
    pending_action: Optional[PendingAction] = None
