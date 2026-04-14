"""OKX crypto price adapter (public API, no key)."""
import asyncio
from datetime import datetime, timezone

import httpx

from infra.cache import cache_key, market_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from schemas.market import MarketQuote

log = get_logger("okx")
BASE_URL = "https://www.okx.com/api/v5/market/ticker"
CANDLES_URL = "https://www.okx.com/api/v5/market/candles"
INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"

_crypto_symbols_cache: set[str] | None = None
_instruments_lock: asyncio.Lock | None = None


def _get_instruments_lock() -> asyncio.Lock:
    global _instruments_lock
    if _instruments_lock is None:
        _instruments_lock = asyncio.Lock()
    return _instruments_lock


async def is_crypto_symbol(symbol: str) -> bool:
    """Check if symbol is a valid OKX spot crypto (vs USDT).

    Cached in-process. Concurrent callers share one HTTP request via
    an asyncio.Lock. On failure, does NOT poison the cache — next call retries.
    """
    global _crypto_symbols_cache
    if _crypto_symbols_cache is not None:
        return symbol.upper() in _crypto_symbols_cache

    async with _get_instruments_lock():
        if _crypto_symbols_cache is not None:
            return symbol.upper() in _crypto_symbols_cache
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(INSTRUMENTS_URL, params={"instType": "SPOT"})
                r.raise_for_status()
                data = r.json().get("data", [])
                _crypto_symbols_cache = {
                    item["baseCcy"].upper()
                    for item in data
                    if item.get("quoteCcy") == "USDT"
                }
        except Exception as e:
            log.warning("okx.instruments.failed", error=str(e))
            return False  # transient — do not cache the failure
    return symbol.upper() in _crypto_symbols_cache


@retry_api(max_attempts=3)
async def _fetch(inst_id: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(BASE_URL, params={"instId": inst_id})
        response.raise_for_status()
        return response.json()


@retry_api(max_attempts=2)
async def _fetch_candles(inst_id: str, bar: str, limit: int) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            CANDLES_URL,
            params={"instId": inst_id, "bar": bar, "limit": str(limit)},
        )
        response.raise_for_status()
        return response.json()


async def get_crypto_history(symbol: str, days: int = 7) -> list[float]:
    """Return daily close prices (oldest → newest) for a sparkline.

    Returns an empty list on failure (never raises). Uses OKX daily candles.
    """
    inst_id = symbol if "-" in symbol else f"{symbol.upper()}-USDT"
    key = cache_key("okx_hist", inst_id, days)
    cache = market_cache()
    if key in cache:
        return cache[key]

    try:
        data = await _fetch_candles(inst_id, bar="1D", limit=days)
        rows = data.get("data") or []
        # OKX returns newest-first; each row: [ts, open, high, low, close, ...]
        closes = [float(r[4]) for r in reversed(rows)]
        cache[key] = closes
        return closes
    except Exception as e:
        log.warning("okx.history.failed", symbol=inst_id, error=str(e))
        return []


async def get_crypto_price(symbol: str) -> MarketQuote:
    """Fetch crypto price from OKX.

    Args:
        symbol: Ticker like "BTC" or full instrument "BTC-USDT".
    """
    inst_id = symbol if "-" in symbol else f"{symbol.upper()}-USDT"
    key = cache_key("okx", inst_id)
    cache = market_cache()

    if key in cache:
        return cache[key]

    breaker = get_breaker("okx")
    if breaker.is_open():
        raise RuntimeError("OKX circuit breaker open")

    try:
        data = await _fetch(inst_id)
        breaker.record_success()

        payload = data.get("data") or []
        if not payload:
            raise ValueError(f"No OKX data for {inst_id}")
        ticker = payload[0]
        last = float(ticker["last"])
        open_24h = float(ticker.get("open24h") or last)
        change_pct = ((last / open_24h) - 1) * 100 if open_24h else 0.0

        quote = MarketQuote(
            symbol=symbol.upper().replace("-USDT", ""),
            category="crypto",
            price=last,
            currency="USD",
            change_pct=change_pct,
            open=open_24h,
            high=float(ticker["high24h"]) if ticker.get("high24h") else None,
            low=float(ticker["low24h"]) if ticker.get("low24h") else None,
            volume=float(ticker["vol24h"]) if ticker.get("vol24h") else None,
            timestamp=datetime.now(timezone.utc),
            source="okx",
        )
        cache[key] = quote
        log.info("okx.fetch", symbol=inst_id, price=quote.price)
        return quote
    except Exception as e:
        breaker.record_failure()
        log.error("okx.fetch.failed", symbol=inst_id, error=str(e))
        raise
