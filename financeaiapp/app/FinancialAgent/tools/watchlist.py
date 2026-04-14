"""Watchlist tools — DynamoDB CRUD via single-table schema.

Plain async helpers (add_watchlist_item / remove_watchlist_item) are the
single implementation reused by both the LangChain @tool wrappers (for
orchestrator agent use) and the direct-action handlers in main.py.
"""
from datetime import datetime, timezone

from langchain_core.tools import tool

from storage.ddb import delete_item, put_item, query_by_sk_prefix
from tools.sources.classifier import classify_ticker


async def add_watchlist_item(symbol: str, category: str = "") -> tuple[str, str]:
    """Add item to watchlist. Returns (symbol, category) as persisted."""
    sym = symbol.upper().strip()
    cat = (category or "").strip() or await classify_ticker(sym)
    put_item(
        f"WATCH#{sym}",
        {
            "symbol": sym,
            "category": cat,
            "added_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return sym, cat


def remove_watchlist_item(symbol: str) -> str:
    """Remove item from watchlist. Returns the normalized symbol."""
    sym = symbol.upper().strip()
    delete_item(f"WATCH#{sym}")
    return sym


@tool
def list_watchlist() -> str:
    """사용자의 관심 종목 전체 목록과 카테고리를 반환합니다."""
    items = query_by_sk_prefix("WATCH#")
    if not items:
        return "관심 종목이 없습니다."
    lines = ["## 관심 종목"]
    for item in items:
        sym = item.get("symbol", "?")
        cat = item.get("category", "?")
        added = (item.get("added_at") or "")[:10]
        lines.append(f"- {sym} ({cat}) — 추가일: {added}")
    return "\n".join(lines)


@tool
async def add_watchlist(symbol: str, category: str = "") -> str:
    """관심 종목에 추가합니다.

    Args:
        symbol: 종목 심볼 (BTC, AAPL, 005930, USD/KRW 등)
        category: crypto/us_stock/kr_stock/fx 중 하나. 비워두면 자동 감지.
    """
    sym, cat = await add_watchlist_item(symbol, category)
    return f"✅ {sym} ({cat}) 관심 종목에 추가됨"


@tool
def remove_watchlist(symbol: str) -> str:
    """관심 종목에서 제거합니다."""
    sym = remove_watchlist_item(symbol)
    return f"🗑️ {sym} 관심 종목에서 제거됨"
