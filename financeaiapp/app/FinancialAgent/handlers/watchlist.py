"""Watchlist HTTP handler — direct JSON endpoint for the frontend.

GET /watchlist returns the user's watchlist enriched with live price,
change %, currency, and a 7-point daily sparkline per item. All price
fetches run in parallel; any per-ticker failure degrades gracefully
(the item is returned without enriched fields).
"""
import asyncio
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from infra.logging_config import get_logger
from schemas.market import MarketQuote
from storage.ddb import query_by_sk_prefix
from tools.sources import alphavantage, frankfurter, okx, pykrx_adapter

log = get_logger("watchlist_handler")

_SPARKLINE_DAYS = 7


async def _quote_for(symbol: str, category: str) -> MarketQuote | None:
    try:
        if category == "crypto":
            return await okx.get_crypto_price(symbol)
        if category == "kr_stock":
            return await pykrx_adapter.get_kr_stock(symbol)
        if category == "fx":
            base, quote = symbol.split("/") if "/" in symbol else ("USD", "KRW")
            return await frankfurter.get_fx(base, quote)
        if category == "us_stock":
            return await alphavantage.get_us_stock(symbol)
    except Exception as e:
        log.warning(
            "watchlist.quote.failed", symbol=symbol, category=category, error=str(e)
        )
    return None


async def _sparkline_for(symbol: str, category: str) -> list[float]:
    try:
        if category == "crypto":
            return await okx.get_crypto_history(symbol, days=_SPARKLINE_DAYS)
        if category == "kr_stock":
            return await pykrx_adapter.get_kr_history(symbol, days=_SPARKLINE_DAYS)
        if category == "fx":
            base, quote = symbol.split("/") if "/" in symbol else ("USD", "KRW")
            return await frankfurter.get_fx_history(
                base, quote, days=_SPARKLINE_DAYS
            )
    except Exception as e:
        log.warning(
            "watchlist.sparkline.failed",
            symbol=symbol,
            category=category,
            error=str(e),
        )
    # US stocks skipped: Alpha Vantage free tier is 25 req/day and a
    # sparkline fetch would burn quota meant for the analyze flow.
    return []


async def _enrich_item(item: dict) -> dict[str, Any]:
    symbol = item.get("symbol", "")
    category = item.get("category", "us_stock")
    quote, sparkline = await asyncio.gather(
        _quote_for(symbol, category),
        _sparkline_for(symbol, category),
        return_exceptions=False,
    )

    enriched: dict[str, Any] = {
        "symbol": symbol,
        "category": category,
        "added_at": item.get("added_at"),
        "sparkline": sparkline,
    }
    if isinstance(quote, MarketQuote):
        enriched["price"] = quote.price
        enriched["currency"] = quote.currency
        enriched["changePct"] = quote.change_pct
        enriched["open"] = quote.open
        enriched["high"] = quote.high
        enriched["low"] = quote.low
        enriched["volume"] = quote.volume
    return enriched


async def get_watchlist_items() -> list[dict[str, Any]]:
    """Core watchlist loader — reusable from both HTTP and entrypoint dispatch.

    Returns the user's watchlist enriched with price/change/sparkline.
    Never raises — returns an empty list on any failure.
    """
    try:
        items = query_by_sk_prefix("WATCH#")
        items = [i for i in items if i.get("symbol")]
        if not items:
            return []

        enriched = await asyncio.gather(
            *[_enrich_item(i) for i in items], return_exceptions=True
        )
        payload: list[dict[str, Any]] = []
        for item, result in zip(items, enriched):
            if isinstance(result, dict):
                payload.append(result)
            else:
                # Fallback to bare item on unexpected failure
                payload.append(
                    {
                        "symbol": item.get("symbol", ""),
                        "category": item.get("category", "us_stock"),
                        "added_at": item.get("added_at"),
                        "sparkline": [],
                    }
                )
        log.info("watchlist.list", count=len(payload))
        return payload
    except Exception:
        log.exception("watchlist.list.failed")
        return []


async def list_watchlist(request: Request) -> JSONResponse:
    """GET /watchlist — HTTP wrapper around get_watchlist_items for local dev."""
    items = await get_watchlist_items()
    return JSONResponse({"items": items})
