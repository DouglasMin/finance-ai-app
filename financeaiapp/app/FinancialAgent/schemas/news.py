"""News data schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    title: str
    url: str
    summary: Optional[str] = None
    source: str  # "naver", "finnhub", "alphavantage"
    published_at: Optional[datetime] = None
    sentiment_score: Optional[float] = None  # -1 to 1
    sentiment_label: Optional[str] = None
    related_tickers: list[str] = Field(default_factory=list)
    lang: str = "en"


class NewsSnapshot(BaseModel):
    items: list[NewsItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    fetched_at: datetime
