"""analyze LangGraph node — LLM synthesis over market + news data.

Uses with_structured_output() to enforce consistent analysis sections:
market_summary, sentiment_overview, news_highlights, risk_factors, outlook,
related_tickers. The structured result is formatted as markdown for the
tool result string.
"""
import threading
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from infra.formatting import format_price, format_volume
from infra.llm import get_llm, get_provider
from infra.logging_config import get_logger
from schemas.analysis import AnalysisResult
from schemas.market import MarketSnapshot
from schemas.news import NewsSnapshot
from storage.snapshots import save_snapshots

log = get_logger("analyze_node")

_init_lock = threading.Lock()
_llm_cache: tuple[object, object, str] | None = None  # (plain, structured, provider)


def _ensure_llms():
    """Return (plain_llm, structured_llm) for the current provider.

    Single source of truth — both instances are always in sync with the
    active provider, eliminating the asymmetric-mutation risk of separate
    getters that shared the same globals.
    """
    global _llm_cache
    provider = get_provider()
    cache = _llm_cache
    if cache is not None and cache[2] == provider:
        return cache[0], cache[1]

    with _init_lock:
        cache = _llm_cache
        if cache is not None and cache[2] == provider:
            return cache[0], cache[1]
        plain = get_llm("analyze")
        structured = plain.with_structured_output(AnalysisResult)
        _llm_cache = (plain, structured, provider)
    return plain, structured


def _get_structured_llm():
    return _ensure_llms()[1]


def _get_plain_llm():
    return _ensure_llms()[0]


_analyze_prompt: str | None = None
_prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "analyze.md"


def _load_prompt() -> str:
    global _analyze_prompt
    if _analyze_prompt is None:
        with _init_lock:
            if _analyze_prompt is None:
                _analyze_prompt = _prompt_path.read_text(encoding="utf-8")
    return _analyze_prompt


def _format_context(
    market: MarketSnapshot, news: NewsSnapshot, query: str
) -> str:
    parts: list[str] = [f"## 사용자 질문\n{query}\n"]

    if market.quotes:
        parts.append("## 시세 데이터")
        for q in market.quotes:
            change_str = f" ({q.change_pct:+.2f}%)" if q.change_pct is not None else ""
            range_str = ""
            if q.high is not None and q.low is not None:
                range_str = (
                    f" | 고가 {format_price(q.high, q.currency)}"
                    f" / 저가 {format_price(q.low, q.currency)}"
                )
            vol_str = ""
            if q.volume is not None:
                vol_str = f" | 거래량 {format_volume(q.volume)}"
            parts.append(
                f"- **{q.symbol}** ({q.category}): "
                f"{format_price(q.price, q.currency)}{change_str}"
                f"{range_str}{vol_str} [{q.source}]"
            )
    if market.errors:
        parts.append(f"\n⚠️ 시세 누락: {', '.join(market.errors[:3])}")

    if news.items:
        parts.append("\n## 뉴스")
        for i, n in enumerate(news.items[:10], 1):
            sentiment = f" [감성: {n.sentiment_label}]" if n.sentiment_label else ""
            source_date = ""
            if n.source:
                source_date += n.source
            if n.published_at:
                source_date += f" · {n.published_at.strftime('%Y-%m-%d')}"
            parts.append(f"{i}. **{n.title}**{sentiment}")
            if source_date:
                parts.append(f"   출처: {source_date}")
            if n.summary:
                parts.append(f"   요약: {n.summary[:200]}")
            if n.url:
                parts.append(f"   원문: {n.url}")

        # Aggregate sentiment from items that have scores
        scored = [n for n in news.items if n.sentiment_score is not None]
        if scored:
            avg = sum(n.sentiment_score for n in scored) / len(scored)
            pos = sum(1 for n in scored if n.sentiment_score > 0.1)
            neg = sum(1 for n in scored if n.sentiment_score < -0.1)
            neu = len(scored) - pos - neg
            label = "긍정" if avg > 0.1 else "부정" if avg < -0.1 else "중립"
            parts.append(
                f"\n## 감성 집계 ({len(scored)}/{len(news.items)}건 분석)\n"
                f"평균: {avg:+.2f} ({label}) | 긍정 {pos}건 · 중립 {neu}건 · 부정 {neg}건"
            )

    if news.errors:
        parts.append(f"\n⚠️ 뉴스 누락: {', '.join(news.errors[:3])}")

    return "\n".join(parts)


def _format_structured_to_markdown(result: AnalysisResult) -> str:
    """Convert AnalysisResult to readable markdown."""
    sections: list[str] = []

    sections.append(f"## 📊 시세 요약\n{result.market_summary}")

    sections.append(f"\n## 🧭 시장 심리\n{result.sentiment_overview}")

    sections.append("\n## 📰 주요 뉴스")
    for h in result.news_highlights:
        sentiment_emoji = {"긍정": "🟢", "부정": "🔴", "중립": "⚪"}.get(
            h.sentiment, "⚪"
        )
        header = f"{sentiment_emoji} **{h.source}**"
        if h.published_at:
            header += f" · {h.published_at}"
        title_line = f"[{h.title}]({h.url})" if h.url else f"**{h.title}**"
        sections.append(f"> {header}")
        sections.append(f"> {title_line}")
        sections.append(f"> → {h.impact}")
        sections.append(">")

    sections.append("\n## ⚠️ 리스크")
    for r in result.risk_factors:
        sections.append(f"- {r}")

    sections.append(f"\n## 🎯 전망\n{result.outlook}")

    sections.append(
        f"\n## 🔗 관련 종목\n{', '.join(f'**{t}**' for t in result.related_tickers)}"
    )

    return "\n".join(sections)


async def analyze_node(state: dict) -> dict:
    market: MarketSnapshot = state["market_data"]
    news: NewsSnapshot = state["news_data"]
    query: str = state.get("query") or ""

    system_prompt = _load_prompt()
    context = _format_context(market, news, query)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context),
    ]

    # Try structured output first, fall back to plain text on transient errors.
    # Schema/validation failures are logged at error level for visibility.
    try:
        structured_llm = _get_structured_llm()
        result = await structured_llm.ainvoke(messages)
        analysis = _format_structured_to_markdown(result)
        log.info("analyze.structured.success", length=len(analysis))
        save_snapshots(state.get("tickers", []), market, result)
        return {"analysis": analysis}
    except ValidationError as e:
        log.error(
            "analyze.structured.validation_failed",
            errors=e.error_count(),
            detail=str(e),
        )
    except Exception as e:
        log.warning("analyze.structured.failed", error=str(e))

    # Fallback: plain text analysis
    try:
        plain_llm = _get_plain_llm()
        response = await plain_llm.ainvoke(messages)
        analysis = response.content if isinstance(response.content, str) else str(response.content)
        log.info("analyze.plain.success", length=len(analysis))
        save_snapshots(state.get("tickers", []), market)
        return {"analysis": analysis}
    except Exception as e:
        log.error("analyze.failed", error=str(e), exc_info=True)
        errors = state.get("errors") or []
        return {
            "analysis": "분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            "errors": errors + [str(e)],
        }
