"""Naver Search API adapter — Korean financial news (25k req/day free)."""
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from infra.cache import cache_key, news_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from infra.secrets import get_secret
from schemas.news import NewsItem, NewsSnapshot

log = get_logger("naver")
BASE_URL = "https://openapi.naver.com/v1/search/news.json"


@retry_api(max_attempts=2)
async def _fetch(query: str, display: int = 10) -> dict:
    cid = get_secret("NAVER_CLIENT_ID")
    csec = get_secret("NAVER_CLIENT_SECRET")
    headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            BASE_URL,
            params={"query": query, "display": display, "sort": "sim"},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


def _strip_html(text: str) -> str:
    return (
        re.sub(r"<[^>]+>", "", text or "")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


_CRYPTO_TERMS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "비트코인", "이더리움", "솔라나", "리플", "도지"}


async def search_naver_news(query: str, display: int = 10) -> NewsSnapshot:
    """Search Korean financial news via Naver.

    Appends context keywords based on whether the query looks crypto-related
    or traditional finance.
    """
    tokens = set(query.upper().split())
    is_crypto = bool(tokens & _CRYPTO_TERMS)
    if is_crypto:
        finance_query = f"{query} 코인 OR 암호화폐 OR 가상자산"
    else:
        finance_query = f"{query} 주식 OR 증시 OR 금융"
    key_c = cache_key("naver_news", finance_query, display)
    cache = news_cache()
    if key_c in cache:
        return cache[key_c]

    breaker = get_breaker("naver")
    if breaker.is_open():
        return NewsSnapshot(
            items=[], errors=["circuit open"], fetched_at=datetime.now(timezone.utc)
        )

    try:
        data = await _fetch(finance_query, display)
        breaker.record_success()

        items: list[NewsItem] = []
        for raw in data.get("items", []):
            pub_at = None
            try:
                pub_at = parsedate_to_datetime(raw.get("pubDate", ""))
            except Exception:
                pub_at = None

            items.append(
                NewsItem(
                    title=_strip_html(raw.get("title", "")),
                    url=raw.get("link") or raw.get("originallink") or "",
                    summary=_strip_html(raw.get("description", "")),
                    source="naver",
                    published_at=pub_at,
                    lang="ko",
                )
            )
        snapshot = NewsSnapshot(items=items, fetched_at=datetime.now(timezone.utc))
        cache[key_c] = snapshot
        log.info("naver.fetch", query=query, count=len(items))
        return snapshot
    except Exception as e:
        breaker.record_failure()
        log.error("naver.fetch.failed", error=str(e))
        return NewsSnapshot(
            items=[], errors=[str(e)], fetched_at=datetime.now(timezone.utc)
        )
