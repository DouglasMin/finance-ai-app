"""fetch_news LangGraph node — parallel news fetch.

Primary source: Google News RSS (free-text keyword search, no API key).
Supplementary sources:
- Korean: Naver (when key present)
- US tickers: Finnhub company news + Alpha Vantage sentiment scoring

News language is chosen by ticker type, not user-query language:
- Crypto / US stocks → English (richer coverage from Bloomberg/Reuters/CoinDesk)
- Korean stocks → Korean (domestic coverage is better)
- No tickers → fall back to the user's query language

Pure Python, no LLM. All sources run in parallel with graceful degrade
— any single failure is captured in the returned NewsSnapshot.errors.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from infra.logging_config import get_logger
from schemas.news import NewsItem, NewsSnapshot
from tools.sources import alphavantage, coingecko, finnhub, googlenews, naver
from tools.sources.classifier import classify_tickers

log = get_logger("fetch_news_node")


async def _build_en_query(
    crypto_tickers: list[str], other_tickers: list[str]
) -> str:
    """Build an English query — crypto gets full name from CoinGecko,
    other tickers are used as-is (Alpha Vantage / equity tickers are
    already globally searchable).
    """
    parts: list[str] = []
    for t in crypto_tickers[:3]:
        name = await coingecko.get_coin_name(t)
        parts.append(f"{name} {t.upper()}" if name else t.upper())
    for t in other_tickers[: max(0, 3 - len(parts))]:
        parts.append(t.upper())
    return " ".join(parts) if parts else ""


def _build_ko_query(query: str, tickers: list[str]) -> str:
    """Use the user's Korean query when present; otherwise fall back to tickers."""
    if query.strip():
        return query.strip()
    return " ".join(tickers[:3])


async def fetch_news_node(state: dict) -> dict:
    query: str = state.get("query") or ""
    tickers: list[str] = state.get("tickers") or []
    user_lang: str = state.get("lang") or "ko"

    coros: list[Any] = []

    buckets = await classify_tickers(tickers)
    kr_tickers = buckets["kr_stock"]
    us_tickers = buckets["us_stock"]
    crypto_tickers = buckets["crypto"]

    has_kr_asset = bool(kr_tickers)

    # Google News: always fetch English for quality global coverage,
    # plus Korean when relevant. English query uses ticker names
    # (not user's Korean text) to guarantee good search results.
    en_query = await _build_en_query(
        crypto_tickers, us_tickers + kr_tickers
    )
    ko_query = _build_ko_query(query, tickers)

    # English Google News — always fetch if we have any tickers or query
    if en_query:
        coros.append(
            googlenews.search_google_news(en_query, lang="en", limit=8)
        )
    elif query.strip():
        coros.append(
            googlenews.search_google_news(query.strip(), lang="en", limit=8)
        )

    # Korean Google News — when Korean assets or Korean user
    if has_kr_asset or (user_lang == "ko" and ko_query):
        coros.append(
            googlenews.search_google_news(ko_query, lang="ko", limit=6)
        )

    # Supplementary: Korean native news via Naver (when key configured).
    # Always use ticker-based query — raw query can be a full briefing prompt.
    if (user_lang == "ko" or kr_tickers) and tickers:
        naver_q = " ".join(tickers[:3])
        coros.append(
            naver.search_naver_news(
                naver_q, display=5, is_crypto=bool(crypto_tickers)
            )
        )

    # Supplementary: US ticker-specific news + sentiment scoring
    if us_tickers:
        # Cap to 3 tickers to respect Alpha Vantage / Finnhub rate limits
        for t in us_tickers[:3]:
            coros.append(finnhub.get_company_news(t))
        coros.append(alphavantage.get_sentiment_news(us_tickers[:3]))

    if not coros:
        log.warning(
            "fetch_news_node.no_sources",
            query=query,
            tickers=tickers,
            lang=user_lang,
        )
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

    # Cap total items to keep the analyze-node LLM context lean
    return {
        "news_data": NewsSnapshot(
            items=items[:15],
            errors=errors,
            fetched_at=datetime.now(timezone.utc),
        )
    }
