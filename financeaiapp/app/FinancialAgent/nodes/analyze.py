"""analyze LangGraph node — LLM synthesis over market + news data.

This is the ONLY node in the research subgraph that calls an LLM. It
receives structured MarketSnapshot + NewsSnapshot, formats them into a
context string, and asks the analyze model to produce a structured analysis.
"""
import os

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import get_llm
from infra.logging_config import get_logger
from schemas.market import MarketSnapshot
from schemas.news import NewsSnapshot

log = get_logger("analyze_node")


def _load_prompt() -> str:
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "prompts", "analyze.md"
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _format_context(
    market: MarketSnapshot, news: NewsSnapshot, query: str
) -> str:
    parts: list[str] = [f"## 사용자 질문\n{query}\n"]

    if market.quotes:
        parts.append("## 시세 데이터")
        for q in market.quotes:
            change_str = f" ({q.change_pct:+.2f}%)" if q.change_pct is not None else ""
            parts.append(
                f"- **{q.symbol}** ({q.category}): {q.currency} {q.price:,.2f}{change_str} [{q.source}]"
            )
    if market.errors:
        parts.append(f"\n⚠️ 시세 누락: {', '.join(market.errors[:3])}")

    if news.items:
        parts.append("\n## 뉴스")
        for i, n in enumerate(news.items[:10], 1):
            sentiment = f" [감성: {n.sentiment_label}]" if n.sentiment_label else ""
            parts.append(f"{i}. {n.title}{sentiment}")
            if n.summary:
                parts.append(f"   요약: {n.summary[:200]}")
            if n.url:
                parts.append(f"   링크: {n.url}")
    if news.errors:
        parts.append(f"\n⚠️ 뉴스 누락: {', '.join(news.errors[:3])}")

    return "\n".join(parts)


async def analyze_node(state: dict) -> dict:
    market: MarketSnapshot = state["market_data"]
    news: NewsSnapshot = state["news_data"]
    query: str = state.get("query") or ""

    system_prompt = _load_prompt()
    context = _format_context(market, news, query)

    llm = get_llm("analyze")

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=context),
            ]
        )
        analysis = response.content if isinstance(response.content, str) else str(response.content)
        log.info("analyze.success", length=len(analysis))
        return {"analysis": analysis}
    except Exception as e:
        log.error("analyze.failed", error=str(e))
        errors = state.get("errors") or []
        return {
            "analysis": f"분석 실패: {e}",
            "errors": errors + [str(e)],
        }
