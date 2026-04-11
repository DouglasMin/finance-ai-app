"""Briefing record schema."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


BriefingStatus = Literal["pending", "in_progress", "partial", "success", "failed"]


class BriefingRecord(BaseModel):
    date: str  # "2026-04-11"
    time_of_day: Literal["AM", "PM"]
    status: BriefingStatus
    content: str = ""
    tickers_covered: list[str] = Field(default_factory=list)
    generated_at: datetime
    duration_ms: int = 0
    errors: list[str] = Field(default_factory=list)
