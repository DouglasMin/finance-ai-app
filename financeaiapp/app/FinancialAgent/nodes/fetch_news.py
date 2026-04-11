"""fetch_news LangGraph node — parallel news fetch.

Routes by lang:
- Korean (lang='ko') or Korean-looking query → Naver search
- US tickers → Finnhub company news + Alpha Vantage sentiment

Pure Python, no LLM.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from infra.logging_config import get_logger
from schemas.news import NewsItem, NewsSnapshot
from tools.sources import alphavantage, finnhub, naver

log = get_logger("fetch_news_node")

_KNOWN_CRYPTOS = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "DOT", "LINK", "AVAX",
    "MATIC", "TRX", "LTC", "BCH", "ATOM", "NEAR", "APT", "ARB", "OP",
}


def _is_us_ticker(ticker: str) -> bool:
    t = ticker.upper()
    if "/" in t:
        return False
    if t.isdigit():
        return False
    if t in _KNOWN_CRYPTOS or t.endswith("-USDT"):
        return False
    return True


async def fetch_news_node(state: dict) -> dict:
    query: str = state.get("query") or ""
    tickers: list[str] = state.get("tickers") or []
    lang: str = state.get("lang") or "ko"

    coros: list[Any] = []

    # Korean news via Naver
    if lang == "ko" and query:
        coros.append(naver.search_naver_news(query, display=5))

    # US news via Finnhub + Alpha Vantage sentiment
    us_tickers = [t for t in tickers if _is_us_ticker(t)]
    if us_tickers:
        # Limit to 3 tickers to avoid rate limits
        for t in us_tickers[:3]:
            coros.append(finnhub.get_company_news(t))
        coros.append(alphavantage.get_sentiment_news(us_tickers[:3]))

    if not coros:
        return {
            "news_data": NewsSnapshot(fetched_at=datetime.now(timezone.utc))
        }

    results = await asyncio.gather(*coros, return_exceptions=True)

    items: list[NewsItem] = []
    errors: list[str] = []
    for r in results:
        if isinstance(r, NewsSnapshot):
            items.extend(r.items)
            errors.extend(r.errors)
        elif isinstance(r, Exception):
            errors.append(str(r))

    # Cap total items to keep LLM context lean
    return {
        "news_data": NewsSnapshot(
            items=items[:15],
            errors=errors,
            fetched_at=datetime.now(timezone.utc),
        )
    }
