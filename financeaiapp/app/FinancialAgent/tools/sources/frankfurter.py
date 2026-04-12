"""Frankfurter FX adapter — free ECB-backed, no key needed."""
from datetime import datetime, timedelta, timezone

import httpx

from infra.cache import cache_key, market_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from schemas.market import MarketQuote

log = get_logger("frankfurter")
BASE_URL = "https://api.frankfurter.dev/v1/latest"
TIMESERIES_URL = "https://api.frankfurter.dev/v1"


@retry_api(max_attempts=3)
async def _fetch(base: str, symbols: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            BASE_URL, params={"base": base, "symbols": symbols}
        )
        response.raise_for_status()
        return response.json()


@retry_api(max_attempts=2)
async def _fetch_timeseries(
    start: str, end: str, base: str, symbols: str
) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{TIMESERIES_URL}/{start}..{end}",
            params={"base": base, "symbols": symbols},
        )
        response.raise_for_status()
        return response.json()


async def get_fx_history(
    base: str = "USD", quote: str = "KRW", days: int = 7
) -> list[float]:
    """Return daily FX rates (oldest → newest) for a sparkline."""
    key = cache_key("frankfurter_hist", base, quote, days)
    cache = market_cache()
    if key in cache:
        return cache[key]

    try:
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=days + 3)).isoformat()
        end = today.isoformat()
        data = await _fetch_timeseries(
            start, end, base.upper(), quote.upper()
        )
        rates = data.get("rates") or {}
        # Date-keyed dict; sort by date and take last `days` values
        sorted_dates = sorted(rates.keys())
        series = [
            float(rates[d][quote.upper()])
            for d in sorted_dates
            if quote.upper() in rates[d]
        ][-days:]
        cache[key] = series
        return series
    except Exception as e:
        log.warning("frankfurter.history.failed", pair=f"{base}/{quote}", error=str(e))
        return []


async def get_fx(base: str = "USD", quote: str = "KRW") -> MarketQuote:
    """Fetch FX rate via Frankfurter."""
    key = cache_key("frankfurter", base.upper(), quote.upper())
    cache = market_cache()
    if key in cache:
        return cache[key]

    breaker = get_breaker("frankfurter")
    if breaker.is_open():
        raise RuntimeError("Frankfurter circuit open")

    try:
        data = await _fetch(base.upper(), quote.upper())
        breaker.record_success()

        rate = float(data["rates"][quote.upper()])
        q = MarketQuote(
            symbol=f"{base.upper()}/{quote.upper()}",
            category="fx",
            price=rate,
            currency=quote.upper(),
            timestamp=datetime.now(timezone.utc),
            source="frankfurter",
        )
        cache[key] = q
        log.info("frankfurter.fetch", pair=f"{base}/{quote}", rate=rate)
        return q
    except Exception as e:
        breaker.record_failure()
        log.error("frankfurter.fetch.failed", error=str(e))
        raise
