"""Pydantic schemas for the AgentCore invoke entrypoint payload."""
from typing import Literal, Optional
from pydantic import BaseModel


class InvokeChatPayload(BaseModel):
    action: Literal["chat"] = "chat"
    session_id: str
    message: str
    correlation_id: Optional[str] = None


class InvokeBriefingPayload(BaseModel):
    action: Literal["briefing"] = "briefing"
    time_of_day: Literal["AM", "PM"]
    correlation_id: Optional[str] = None
