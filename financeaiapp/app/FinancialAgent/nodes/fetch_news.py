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
from tools.sources import alphavantage, finnhub, googlenews, naver, okx

log = get_logger("fetch_news_node")


def _is_kr_ticker(ticker: str) -> bool:
    """Korean stock codes are 6-digit numeric."""
    return ticker.isdigit() and len(ticker) == 6


async def _classify_tickers(tickers: list[str]) -> dict[str, list[str]]:
    """Classify tickers into {crypto, us_stock, kr_stock, fx} via OKX lookup."""
    buckets: dict[str, list[str]] = {
        "crypto": [], "us_stock": [], "kr_stock": [], "fx": [],
    }
    for t in tickers:
        u = t.upper().strip()
        if "/" in u:
            buckets["fx"].append(t)
        elif _is_kr_ticker(u):
            buckets["kr_stock"].append(t)
        elif u.endswith("-USDT") or u.endswith("-USD") or await okx.is_crypto_symbol(u):
            buckets["crypto"].append(t)
        else:
            buckets["us_stock"].append(t)
    return buckets


_TICKER_NAMES: dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "XRP Ripple",
    "DOGE": "Dogecoin", "ADA": "Cardano", "DOT": "Polkadot", "LINK": "Chainlink",
    "AVAX": "Avalanche", "MATIC": "Polygon", "TRX": "Tron", "LTC": "Litecoin",
    "ATOM": "Cosmos", "NEAR": "NEAR Protocol", "APT": "Aptos", "ARB": "Arbitrum",
    "OP": "Optimism",
}


def _build_en_query(tickers: list[str]) -> str:
    """Build an English search query from tickers using full asset names."""
    parts: list[str] = []
    for t in tickers[:3]:
        name = _TICKER_NAMES.get(t.upper())
        if name:
            parts.append(f"{name} {t.upper()}")
        else:
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

    buckets = await _classify_tickers(tickers)
    kr_tickers = buckets["kr_stock"]
    us_tickers = buckets["us_stock"]
    crypto_tickers = buckets["crypto"]

    has_global_asset = bool(crypto_tickers or us_tickers)
    has_kr_asset = bool(kr_tickers)

    # Google News: always fetch English for quality global coverage,
    # plus Korean when relevant. English query uses ticker names
    # (not user's Korean text) to guarantee good search results.
    en_query = _build_en_query(crypto_tickers + us_tickers + kr_tickers)
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
        if crypto_tickers:
            naver_q += " 코인 OR 암호화폐"
        else:
            naver_q += " 주식 OR 증시"
        coros.append(naver.search_naver_news(naver_q, display=5))

    # Supplementary: US ticker-specific news + sentiment scoring
    if us_tickers:
        # Cap to 3 tickers to respect Alpha Vantage / Finnhub rate limits
        for t in us_tickers[:3]:
            coros.append(finnhub.get_company_news(t))
        coros.append(alphavantage.get_sentiment_news(us_tickers[:3]))

    if not coros:
        log.warning(
            "fetch_news_node.no_sources", query=query, tickers=tickers, lang=lang
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
