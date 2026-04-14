"""fetch_market LangGraph node — parallel market data fetch across sources.

Pure Python, no LLM. Dispatches tickers to the right adapter based on
category detection, runs them in parallel with asyncio.gather, and returns
a MarketSnapshot (with partial-failure tolerance).
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from infra.logging_config import get_logger
from schemas.market import MarketQuote, MarketSnapshot
from tools.sources import alphavantage, frankfurter, okx, pykrx_adapter
from tools.sources.classifier import classify_ticker

log = get_logger("fetch_market_node")


async def _fetch_one(ticker: str) -> MarketQuote | None:
    category = await classify_ticker(ticker)
    try:
        if category == "crypto":
            return await okx.get_crypto_price(ticker)
        if category == "us_stock":
            return await alphavantage.get_us_stock(ticker)
        if category == "kr_stock":
            return await pykrx_adapter.get_kr_stock(ticker)
        if category == "fx":
            base, quote = ticker.split("/")
            return await frankfurter.get_fx(base, quote)
    except Exception as e:
        log.warning("fetch_market.ticker.failed", ticker=ticker, error=str(e))
    return None


async def fetch_market_node(state: dict) -> dict:
    tickers: list[str] = state.get("tickers") or []
    if not tickers:
        return {
            "market_data": MarketSnapshot(fetched_at=datetime.now(timezone.utc))
        }

    results: list[Any] = await asyncio.gather(
        *[_fetch_one(t) for t in tickers], return_exceptions=True
    )

    quotes: list[MarketQuote] = []
    errors: list[str] = []
    for ticker, result in zip(tickers, results):
        if isinstance(result, MarketQuote):
            quotes.append(result)
        elif isinstance(result, Exception):
            errors.append(f"{ticker}: {result}")
        elif result is None:
            errors.append(f"{ticker}: no data")

    return {
        "market_data": MarketSnapshot(
            quotes=quotes,
            errors=errors,
            fetched_at=datetime.now(timezone.utc),
        )
    }
