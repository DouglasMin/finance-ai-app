"""Paper trading DDB helpers — portfolio, positions, orders, strategies, PnL.

All functions build on the generic ddb.py helpers (put_item, get_item, etc.)
using the SK patterns defined in the Phase 2 design:

  PORTFOLIO           — single item per user
  POSITION#{symbol}   — one per held asset
  ORDER#{ulid}        — time-sortable order history
  STRATEGY#{name}     — registered strategies
  STRATLOG#{name}#{ulid} — strategy trigger log
  PNL#{yyyy-mm-dd}    — daily portfolio snapshot
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from ulid import ULID

from schemas.trading import (
    Order,
    PnlSnapshot,
    Portfolio,
    Position,
    Strategy,
)
from storage.ddb import delete_item, get_item, put_item, query_by_sk_prefix


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(val: object) -> float:
    """Convert DDB Decimal/int/float to float safely; 0.0 for None/unparseable."""
    if val is None:
        return 0.0
    if isinstance(val, (Decimal, int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

def get_portfolio() -> Optional[Portfolio]:
    item = get_item("PORTFOLIO")
    if not item:
        return None
    return Portfolio(
        initial_capital=_to_float(item.get("initial_capital")),
        cash_balance=_to_float(item.get("cash_balance")),
        realized_pnl=_to_float(item.get("realized_pnl", 0)),
        currency=item.get("currency", "USD"),
        created_at=item.get("created_at", _now_iso()),
    )


def upsert_portfolio(portfolio: Portfolio) -> None:
    put_item("PORTFOLIO", portfolio.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def _item_to_position(i: dict) -> Position:
    return Position(
        symbol=i["symbol"],
        category=i.get("category", "us_stock"),
        quantity=_to_float(i["quantity"]),
        avg_cost=_to_float(i["avg_cost"]),
        currency=i.get("currency", "USD"),
        opened_at=i.get("opened_at", _now_iso()),
        updated_at=i.get("updated_at", _now_iso()),
    )


def get_position(symbol: str) -> Optional[Position]:
    item = get_item(f"POSITION#{symbol.upper()}")
    if not item:
        return None
    return _item_to_position(item)


def upsert_position(position: Position) -> None:
    put_item(f"POSITION#{position.symbol}", position.model_dump(mode="json"))


def delete_position(symbol: str) -> None:
    delete_item(f"POSITION#{symbol.upper()}")


def list_positions() -> list[Position]:
    items = query_by_sk_prefix("POSITION#")
    return [_item_to_position(i) for i in items]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def create_order(order: Order) -> None:
    """Persist order. order.order_id should be a pre-generated ULID."""
    put_item(f"ORDER#{order.order_id}", order.model_dump(mode="json"))


def new_order_id() -> str:
    """Generate a time-sortable ULID for order SK."""
    return str(ULID())


def list_orders(limit: int = 20) -> list[Order]:
    items = query_by_sk_prefix("ORDER#", limit=limit, ascending=False)
    return [
        Order(
            order_id=i.get("order_id", ""),
            symbol=i["symbol"],
            side=i["side"],
            quantity=_to_float(i["quantity"]),
            price=_to_float(i["price"]),
            total_cost=_to_float(i.get("total_cost", 0)),
            currency=i.get("currency", "USD"),
            status=i.get("status", "filled"),
            created_at=i.get("created_at", _now_iso()),
        )
        for i in items
    ]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def _item_to_strategy(i: dict) -> Strategy:
    return Strategy(
        name=i["name"],
        description=i.get("description", ""),
        target_symbol=i["target_symbol"],
        condition_type=i["condition_type"],
        threshold=_to_float(i["threshold"]),
        action=i["action"],
        quantity=_to_float(i["quantity"]) if i.get("quantity") else None,
        enabled=i.get("enabled", True),
        created_at=i.get("created_at", _now_iso()),
        last_triggered=i.get("last_triggered"),
        trigger_count=int(i.get("trigger_count", 0)),
    )


def get_strategy(name: str) -> Optional[Strategy]:
    item = get_item(f"STRATEGY#{name}")
    if not item:
        return None
    return _item_to_strategy(item)


def upsert_strategy(strategy: Strategy) -> None:
    put_item(f"STRATEGY#{strategy.name}", strategy.model_dump(mode="json"))


def delete_strategy(name: str) -> None:
    delete_item(f"STRATEGY#{name}")


def list_strategies() -> list[Strategy]:
    items = query_by_sk_prefix("STRATEGY#")
    return [_item_to_strategy(i) for i in items]


def log_strategy_trigger(name: str, details: dict) -> None:
    """Log a strategy trigger event (STRATLOG#{name}#{ulid})."""
    ulid = str(ULID())
    put_item(f"STRATLOG#{name}#{ulid}", {
        **details,  # caller data first — reserved keys below win
        "strategy_name": name,
        "trigger_id": ulid,
    })


# ---------------------------------------------------------------------------
# PnL Snapshots
# ---------------------------------------------------------------------------

def save_pnl_snapshot(snapshot: PnlSnapshot) -> None:
    put_item(f"PNL#{snapshot.date}", snapshot.model_dump(mode="json"))


def list_pnl_snapshots(limit: int = 30) -> list[PnlSnapshot]:
    items = query_by_sk_prefix("PNL#", limit=limit, ascending=False)
    return [
        PnlSnapshot(
            date=i.get("date", ""),
            total_value=_to_float(i.get("total_value", 0)),
            cash=_to_float(i.get("cash", 0)),
            unrealized_pnl=_to_float(i.get("unrealized_pnl", 0)),
            realized_pnl=_to_float(i.get("realized_pnl", 0)),
            positions_count=int(i.get("positions_count", 0)),
        )
        for i in items
    ]
