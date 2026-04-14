"""News previews tool — fetches news and returns formatted preview cards with links.

Standalone tool for the orchestrator. Uses the same adapters as the research
subgraph but returns formatted markdown cards directly (no LLM analysis).
"""
import asyncio
from datetime import datetime, timezone

from langchain_core.tools import tool

from infra.logging_config import get_logger
from nodes.fetch_news import (
    _build_en_query,
    _build_ko_query,
    _classify_tickers,
    _is_kr_ticker,
)
from schemas.news import NewsItem, NewsSnapshot
from tools.sources import alphavantage, finnhub, googlenews, naver

log = get_logger("news_previews")


def _format_preview_cards(items: list[NewsItem]) -> str:
    """Format news items as markdown blockquote cards with links."""
    if not items:
        return "관련 뉴스를 찾지 못했습니다."

    cards: list[str] = []
    for item in items:
        sentiment_emoji = ""
        if item.sentiment_label:
            sentiment_emoji = {
                "Bullish": "🟢", "Somewhat-Bullish": "🟢",
                "Bearish": "🔴", "Somewhat-Bearish": "🔴",
                "Neutral": "⚪",
            }.get(item.sentiment_label, "⚪") + " "

        header = f"{sentiment_emoji}**{item.source}**"
        if item.published_at:
            header += f" · {item.published_at.strftime('%Y-%m-%d')}"

        if item.url:
            title_line = f"[{item.title}]({item.url})"
        else:
            title_line = f"**{item.title}**"

        card = f"> {header}\n> {title_line}"
        if item.summary and item.summary != item.title:
            card += f"\n> {item.summary[:150]}"
        card += "\n>"

        cards.append(card)

    return "\n\n".join(cards)


@tool
async def fetch_news_previews(
    query: str,
    tickers: list[str] | None = None,
    lang: str = "ko",
) -> str:
    """뉴스 미리보기 도구. 관련 뉴스 기사 목록을 출처, 날짜, 원문 링크와 함께 반환합니다.

    시세 분석 없이 뉴스 링크만 필요할 때 사용하세요.
    research 도구와 달리 LLM 분석 없이 뉴스 데이터만 빠르게 반환합니다.

    Args:
        query: 검색 키워드 (예: "BTC 뉴스", "삼성전자 실적")
        tickers: 관련 종목 리스트 (예: ["BTC"], ["AAPL", "NVDA"])
        lang: 응답 언어 ("ko" 또는 "en", 기본 ko)

    Returns:
        뉴스 미리보기 카드 (제목 + 출처 + 날짜 + 원문 링크)
    """
    tickers = tickers or []
    coros: list = []

    buckets = await _classify_tickers(tickers)
    kr_tickers = buckets["kr_stock"]
    us_tickers = buckets["us_stock"]
    crypto_tickers = buckets["crypto"]

    # English Google News (ticker-based query for better results)
    en_query = _build_en_query(crypto_tickers + us_tickers + kr_tickers)
    if en_query:
        coros.append(googlenews.search_google_news(en_query, lang="en", limit=5))
    elif query.strip():
        coros.append(googlenews.search_google_news(query.strip(), lang="en", limit=5))

    # Korean Google News
    ko_query = _build_ko_query(query, tickers)
    if lang == "ko" and ko_query:
        coros.append(googlenews.search_google_news(ko_query, lang="ko", limit=5))

    # Naver (Korean)
    if lang == "ko" and query:
        coros.append(naver.search_naver_news(query, display=5))

    # Finnhub + AV for US tickers
    if us_tickers:
        for t in us_tickers[:2]:
            coros.append(finnhub.get_company_news(t))
        coros.append(alphavantage.get_sentiment_news(us_tickers[:2]))

    if not coros:
        return "검색어 또는 종목을 지정해주세요."

    results = await asyncio.gather(*coros, return_exceptions=True)

    all_items: list[NewsItem] = []
    for r in results:
        if isinstance(r, NewsSnapshot):
            all_items.extend(r.items)

    # Sort by date (newest first), limit to 10
    all_items.sort(
        key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    all_items = all_items[:10]

    log.info("news_previews.fetch", query=query, count=len(all_items))
    return _format_preview_cards(all_items)
