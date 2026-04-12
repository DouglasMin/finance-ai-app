"""Alpha Vantage adapter — US stocks + finance-specific news sentiment."""
from datetime import datetime, timezone

import httpx

from infra.cache import cache_key, market_cache, news_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from infra.secrets import get_secret
from schemas.market import MarketQuote
from schemas.news import NewsItem, NewsSnapshot

log = get_logger("alphavantage")
BASE_URL = "https://www.alphavantage.co/query"


@retry_api(max_attempts=2)
async def _call(params: dict) -> dict:
    key = get_secret("ALPHA_VANTAGE_API_KEY")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(BASE_URL, params={**params, "apikey": key})
        response.raise_for_status()
        return response.json()


async def get_us_stock(symbol: str) -> MarketQuote:
    """Fetch a US stock snapshot via GLOBAL_QUOTE."""
    key_c = cache_key("av_stock", symbol.upper())
    cache = market_cache()
    if key_c in cache:
        return cache[key_c]

    breaker = get_breaker("alphavantage")
    if breaker.is_open():
        raise RuntimeError("Alpha Vantage circuit breaker open")

    try:
        data = await _call({"function": "GLOBAL_QUOTE", "symbol": symbol.upper()})
        breaker.record_success()
        quote_data = data.get("Global Quote") or {}
        if not quote_data:
            raise ValueError(f"No Alpha Vantage data for {symbol}")

        price = float(quote_data["05. price"])
        change_pct_str = (quote_data.get("10. change percent") or "0%").rstrip("%")

        quote = MarketQuote(
            symbol=symbol.upper(),
            category="us_stock",
            price=price,
            currency="USD",
            change_pct=float(change_pct_str) if change_pct_str else None,
            open=float(quote_data["02. open"]) if quote_data.get("02. open") else None,
            high=float(quote_data["03. high"]) if quote_data.get("03. high") else None,
            low=float(quote_data["04. low"]) if quote_data.get("04. low") else None,
            volume=float(quote_data["06. volume"]) if quote_data.get("06. volume") else None,
            timestamp=datetime.now(timezone.utc),
            source="alphavantage",
        )
        cache[key_c] = quote
        log.info("av.get_us_stock", symbol=symbol, price=price)
        return quote
    except Exception as e:
        breaker.record_failure()
        log.error("av.get_us_stock.failed", symbol=symbol, error=str(e))
        raise


async def get_sentiment_news(tickers: list[str], limit: int = 10) -> NewsSnapshot:
    """Alpha Vantage NEWS_SENTIMENT — pre-scored finance news."""
    sorted_tickers = ",".join(sorted(t.upper() for t in tickers))
    key_c = cache_key("av_news", sorted_tickers, limit)
    cache = news_cache()
    if key_c in cache:
        return cache[key_c]

    breaker = get_breaker("alphavantage")
    if breaker.is_open():
        return NewsSnapshot(
            items=[],
            errors=["circuit open"],
            fetched_at=datetime.now(timezone.utc),
        )

    try:
        data = await _call(
            {
                "function": "NEWS_SENTIMENT",
                "tickers": sorted_tickers,
                "limit": limit,
                "sort": "LATEST",
            }
        )
        breaker.record_success()

        items: list[NewsItem] = []
        for feed in (data.get("feed") or [])[:limit]:
            related = [t.get("ticker", "") for t in (feed.get("ticker_sentiment") or [])]
            sentiment_score = feed.get("overall_sentiment_score")
            items.append(
                NewsItem(
                    title=feed.get("title", ""),
                    url=feed.get("url", ""),
                    summary=feed.get("summary"),
                    source="alphavantage",
                    sentiment_score=float(sentiment_score) if sentiment_score is not None else None,
                    sentiment_label=feed.get("overall_sentiment_label"),
                    related_tickers=[t for t in related if t],
                    lang="en",
                )
            )
        snapshot = NewsSnapshot(items=items, fetched_at=datetime.now(timezone.utc))
        cache[key_c] = snapshot
        return snapshot
    except Exception as e:
        breaker.record_failure()
        log.error("av.get_sentiment_news.failed", error=str(e))
        return NewsSnapshot(
            items=[],
            errors=[str(e)],
            fetched_at=datetime.now(timezone.utc),
        )
