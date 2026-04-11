"""Finnhub company news adapter."""
from datetime import datetime, timedelta, timezone

import httpx

from infra.cache import cache_key, news_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from infra.secrets import get_secret
from schemas.news import NewsItem, NewsSnapshot

log = get_logger("finnhub")
BASE_URL = "https://finnhub.io/api/v1"


@retry_api(max_attempts=3)
async def _fetch(path: str, params: dict) -> list:
    key = get_secret("FINNHUB_API_KEY")
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{BASE_URL}{path}", params={**params, "token": key}
        )
        response.raise_for_status()
        return response.json()


async def get_company_news(symbol: str, days: int = 3) -> NewsSnapshot:
    """Fetch company-specific news from Finnhub."""
    key_c = cache_key("finnhub_news", symbol.upper(), days)
    cache = news_cache()
    if key_c in cache:
        return cache[key_c]

    breaker = get_breaker("finnhub")
    if breaker.is_open():
        return NewsSnapshot(
            items=[], errors=["circuit open"], fetched_at=datetime.now(timezone.utc)
        )

    try:
        today = datetime.now()
        since = today - timedelta(days=days)
        data = await _fetch(
            "/company-news",
            {
                "symbol": symbol.upper(),
                "from": since.strftime("%Y-%m-%d"),
                "to": today.strftime("%Y-%m-%d"),
            },
        )
        breaker.record_success()

        items: list[NewsItem] = []
        for raw in (data or [])[:10]:
            ts = raw.get("datetime")
            items.append(
                NewsItem(
                    title=raw.get("headline", ""),
                    url=raw.get("url", ""),
                    summary=raw.get("summary"),
                    source="finnhub",
                    published_at=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
                    related_tickers=[symbol.upper()],
                    lang="en",
                )
            )
        snapshot = NewsSnapshot(items=items, fetched_at=datetime.now(timezone.utc))
        cache[key_c] = snapshot
        return snapshot
    except Exception as e:
        breaker.record_failure()
        log.error("finnhub.fetch.failed", error=str(e))
        return NewsSnapshot(
            items=[], errors=[str(e)], fetched_at=datetime.now(timezone.utc)
        )
