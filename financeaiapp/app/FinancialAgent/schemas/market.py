"""Market data schemas."""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


MarketCategory = Literal["crypto", "us_stock", "kr_stock", "fx"]


class MarketQuote(BaseModel):
    symbol: str
    category: MarketCategory
    price: float
    currency: str  # "USD", "KRW", etc.
    change_pct: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    timestamp: datetime
    source: str  # "okx", "alphavantage", "pykrx", "frankfurter"


class MarketSnapshot(BaseModel):
    quotes: list[MarketQuote] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    fetched_at: datetime
