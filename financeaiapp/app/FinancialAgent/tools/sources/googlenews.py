"""Google News RSS adapter — free-text keyword search, no API key required.

Google News search is exposed as an RSS feed at
`https://news.google.com/rss/search`. Unlike ticker-based APIs, it accepts
arbitrary keywords and aggregates global sources (Reuters, Bloomberg,
CoinDesk, etc.). The free tier is effectively unlimited for personal use.
"""
import asyncio
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser
import httpx

from infra.cache import cache_key, news_cache
from infra.circuit_breaker import get_breaker
from infra.logging_config import get_logger
from infra.retry import retry_api
from schemas.news import NewsItem, NewsSnapshot

log = get_logger("googlenews")
BASE_URL = "https://news.google.com/rss/search"

# Locale config per supported language
_LANG_CONFIG: dict[str, dict[str, str]] = {
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
}

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) financial-bot/0.1"
)


@retry_api(max_attempts=2)
async def _fetch_feed(query: str, lang: str) -> str:
    """Fetch the raw RSS XML for a query. Retries on transient failures."""
    locale = _LANG_CONFIG.get(lang, _LANG_CONFIG["en"])
    params = {"q": query, **locale}
    async with httpx.AsyncClient(
        timeout=10.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT}
    ) as client:
        response = await client.get(BASE_URL, params=params)
        response.raise_for_status()
        return response.text


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode all named + numeric entities."""
    no_tags = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(no_tags).strip()


def _extract_source(entry: feedparser.FeedParserDict) -> str:
    """Best-effort source attribution from a feedparser entry."""
    src = entry.get("source") or {}
    return src.get("title") or "googlenews"


def _parse_pub_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        log.debug("googlenews.bad_pubdate", value=value)
        return None


async def search_google_news(
    query: str, lang: str = "en", limit: int = 10
) -> NewsSnapshot:
    """Search global news via Google News RSS by free-text keyword.

    Args:
        query: Search terms (e.g., "Bitcoin price", "AAPL earnings").
        lang: Language/locale — "en" (English/US) or "ko" (Korean/KR).
            Unknown values fall back to English.
        limit: Max items to return. Google typically supplies ~100 per feed.

    Returns:
        NewsSnapshot with up to `limit` NewsItem entries on success; an
        empty snapshot (with `errors` populated) on failure. Never raises.
    """
    key_c = cache_key("gnews", query, lang, limit)
    cache = news_cache()
    if key_c in cache:
        return cache[key_c]

    breaker = get_breaker("googlenews")
    if breaker.is_open():
        return NewsSnapshot(
            items=[],
            errors=["circuit open"],
            fetched_at=datetime.now(timezone.utc),
        )

    try:
        xml = await _fetch_feed(query, lang)
        # feedparser.parse is blocking CPU work — run it off the event loop.
        feed = await asyncio.to_thread(feedparser.parse, xml)

        if feed.bozo:
            if not feed.entries:
                raise ValueError(
                    f"google news parse error: {getattr(feed, 'bozo_exception', 'unknown')}"
                )
            log.warning(
                "googlenews.feed.bozo",
                query=query,
                exc=str(getattr(feed, "bozo_exception", "")),
            )

        breaker.record_success()

        items: list[NewsItem] = []
        for entry in feed.entries[:limit]:
            source_name = _extract_source(entry)
            title = _strip_html(entry.get("title", ""))
            # Google News titles often end with " - SourceName"; trim it.
            if source_name != "googlenews" and title.endswith(f" - {source_name}"):
                title = title[: -(len(source_name) + 3)].strip()

            items.append(
                NewsItem(
                    title=title,
                    url=entry.get("link", ""),
                    summary=_strip_html(entry.get("summary", "")),
                    source=f"gnews:{source_name}",
                    published_at=_parse_pub_date(entry.get("published", "")),
                    lang=lang if lang in _LANG_CONFIG else "en",
                )
            )

        snapshot = NewsSnapshot(
            items=items, fetched_at=datetime.now(timezone.utc)
        )
        cache[key_c] = snapshot
        log.info("googlenews.fetch", query=query, lang=lang, count=len(items))
        return snapshot
    except Exception as e:
        breaker.record_failure()
        log.error("googlenews.fetch.failed", query=query, error=str(e))
        return NewsSnapshot(
            items=[],
            errors=[f"googlenews: {e}"],
            fetched_at=datetime.now(timezone.utc),
        )
