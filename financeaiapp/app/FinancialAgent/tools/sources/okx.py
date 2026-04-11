"""OKX crypto price adapter (public API, no key)."""
from datetime import datetime, timezone

import httpx

from infra.cache import cache_key, market_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from schemas.market import MarketQuote

log = get_logger("okx")
BASE_URL = "https://www.okx.com/api/v5/market/ticker"


@retry_api(max_attempts=3)
async def _fetch(inst_id: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(BASE_URL, params={"instId": inst_id})
        response.raise_for_status()
        return response.json()


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
            volume=float(ticker.get("vol24h") or 0),
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
