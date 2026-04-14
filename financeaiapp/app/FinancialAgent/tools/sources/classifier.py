"""Unified ticker classifier — single source of truth for category detection.

Priority:
  1. Contains "/" → fx (USD/KRW)
  2. 6-digit numeric → kr_stock (KOSPI/KOSDAQ code)
  3. OKX-quoted base currency → crypto (dynamic lookup, no hardcoded list)
  4. -USDT / -USD suffix → crypto
  5. Fallback → us_stock

All crypto detection goes through OKX's live instrument list, so new
coins are supported without code changes.
"""
import asyncio
import re
from typing import Literal

from tools.sources import okx

Category = Literal["crypto", "us_stock", "kr_stock", "fx"]

_KR_CODE = re.compile(r"^\d{6}$")


async def classify_ticker(ticker: str) -> Category:
    t = ticker.upper().strip()
    if "/" in t:
        return "fx"
    if _KR_CODE.fullmatch(t):
        return "kr_stock"
    if t.endswith("-USDT") or t.endswith("-USD"):
        return "crypto"
    if await okx.is_crypto_symbol(t):
        return "crypto"
    return "us_stock"


async def classify_tickers(tickers: list[str]) -> dict[str, list[str]]:
    """Bulk classify — returns {category: [tickers]}. Runs in parallel."""
    buckets: dict[str, list[str]] = {
        "crypto": [], "us_stock": [], "kr_stock": [], "fx": [],
    }
    categories = await asyncio.gather(*(classify_ticker(t) for t in tickers))
    for t, cat in zip(tickers, categories):
        buckets[cat].append(t)
    return buckets
