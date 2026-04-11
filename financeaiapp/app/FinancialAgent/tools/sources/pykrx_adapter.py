"""Korean stock adapter using pykrx (sync library wrapped with asyncio.to_thread)."""
import asyncio
from datetime import datetime, timezone

from pykrx import stock

from infra.cache import cache_key, market_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from schemas.market import MarketQuote

log = get_logger("pykrx")


def _fetch_ohlcv_sync(symbol: str) -> dict:
    """Sync pykrx call — run via asyncio.to_thread()."""
    today = datetime.now().strftime("%Y%m%d")
    # Look back a few days to handle weekends/holidays
    lookback = (datetime.now()).strftime("%Y%m%d")
    start = (datetime.now().replace(day=max(1, datetime.now().day - 7))).strftime("%Y%m%d")
    df = stock.get_market_ohlcv(start, today, symbol)
    if df is None or df.empty:
        raise ValueError(f"No pykrx data for {symbol}")
    row = df.iloc[-1]
    return {
        "close": float(row["종가"]),
        "open": float(row["시가"]),
        "volume": float(row["거래량"]),
    }


async def get_kr_stock(symbol: str) -> MarketQuote:
    """Fetch Korean stock via pykrx. Symbol is 6-digit code like '005930'."""
    key = cache_key("pykrx", symbol)
    cache = market_cache()
    if key in cache:
        return cache[key]

    breaker = get_breaker("pykrx")
    if breaker.is_open():
        raise RuntimeError("pykrx circuit open")

    try:
        data = await asyncio.to_thread(_fetch_ohlcv_sync, symbol)
        breaker.record_success()

        change_pct = (
            (data["close"] / data["open"] - 1) * 100 if data["open"] else 0.0
        )

        quote = MarketQuote(
            symbol=symbol,
            category="kr_stock",
            price=data["close"],
            currency="KRW",
            change_pct=change_pct,
            volume=data["volume"],
            timestamp=datetime.now(timezone.utc),
            source="pykrx",
        )
        cache[key] = quote
        log.info("pykrx.fetch", symbol=symbol, price=quote.price)
        return quote
    except Exception as e:
        breaker.record_failure()
        log.error("pykrx.fetch.failed", symbol=symbol, error=str(e))
        raise
