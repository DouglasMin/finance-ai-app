"""Paper trading schemas — virtual portfolio, positions, orders, strategies."""
import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

OrderSide = Literal["buy", "sell"]
OrderStatus = Literal["filled"]
ConditionType = Literal["price_above", "price_below", "change_pct_above", "change_pct_below"]
StrategyAction = Literal["alert", "buy", "sell"]
MarketCategory = Literal["crypto", "us_stock", "kr_stock", "fx"]


class Portfolio(BaseModel):
    """Virtual portfolio — tracks cash balance and realized PnL."""
    initial_capital: float = Field(gt=0)
    cash_balance: float
    realized_pnl: float = 0.0
    currency: str = "USD"
    created_at: datetime


class Position(BaseModel):
    """Open position in a single asset."""
    symbol: str
    category: MarketCategory
    quantity: float
    avg_cost: float
    currency: str
    opened_at: datetime
    updated_at: datetime

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.upper().strip()


class Order(BaseModel):
    """Filled paper trade order record."""
    order_id: str  # ULID
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    total_cost: float  # price * quantity
    currency: str
    status: OrderStatus = "filled"
    created_at: datetime


class Strategy(BaseModel):
    """Condition-based monitoring strategy."""
    name: str
    description: str = ""
    target_symbol: str
    condition_type: ConditionType
    threshold: float
    action: StrategyAction
    quantity: Optional[float] = None  # None for alert-only
    enabled: bool = True
    created_at: datetime
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0


class PnlSnapshot(BaseModel):
    """Daily portfolio performance snapshot."""
    date: str  # "2026-04-14"
    total_value: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    positions_count: int

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError(f"date must be YYYY-MM-DD, got: {v!r}")
        return v
