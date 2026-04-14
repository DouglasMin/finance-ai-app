"""Watchlist tools — DynamoDB CRUD via single-table schema."""
from datetime import datetime, timezone

from langchain_core.tools import tool

from storage.ddb import delete_item, put_item, query_by_sk_prefix
from tools.sources.okx import is_crypto_symbol


async def _detect_category(symbol: str) -> str:
    s = symbol.upper().strip()
    if "/" in s:
        return "fx"
    if s.isdigit() and len(s) == 6:
        return "kr_stock"
    if s.endswith("-USDT") or await is_crypto_symbol(s):
        return "crypto"
    return "us_stock"


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
    sym = symbol.upper().strip()
    cat = category.strip() or await _detect_category(sym)
    put_item(
        f"WATCH#{sym}",
        {
            "symbol": sym,
            "category": cat,
            "added_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return f"✅ {sym} ({cat}) 관심 종목에 추가됨"


@tool
def remove_watchlist(symbol: str) -> str:
    """관심 종목에서 제거합니다."""
    sym = symbol.upper().strip()
    delete_item(f"WATCH#{sym}")
    return f"🗑️ {sym} 관심 종목에서 제거됨"
