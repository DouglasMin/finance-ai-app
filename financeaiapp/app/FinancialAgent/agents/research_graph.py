"""Research subgraph — parallel fetch_market ∥ fetch_news → analyze.

This is the core retrieval-and-analysis pipeline. Built with LangGraph
StateGraph, uses fan-out from START to both fetch nodes, then fan-in to
the analyze node. Fetch nodes are pure Python (no LLM); analyze node is
the only LLM call on the retrieval path.
"""
import operator
from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from nodes.analyze import analyze_node
from nodes.fetch_market import fetch_market_node
from nodes.fetch_news import fetch_news_node
from schemas.market import MarketSnapshot
from schemas.news import NewsSnapshot


@dataclass
class ResearchResult:
    """Structured research output — content plus source-level error flags.

    Callers (e.g. briefing handler) can use the error lists to decide
    `partial` vs `success` status without scraping LLM output text.
    """
    content: str
    market_errors: list[str] = field(default_factory=list)
    news_errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.market_errors or self.news_errors)


class ResearchState(TypedDict):
    query: str
    tickers: list[str]
    lang: Literal["ko", "en"]
    market_data: Optional[MarketSnapshot]
    news_data: Optional[NewsSnapshot]
    analysis: Optional[str]
    errors: Annotated[list[str], operator.add]


def build_research_graph():
    g = StateGraph(ResearchState)
    g.add_node("fetch_market", fetch_market_node)
    g.add_node("fetch_news", fetch_news_node)
    g.add_node("analyze", analyze_node)

    # Fan-out: both fetches run in parallel from START
    g.add_edge(START, "fetch_market")
    g.add_edge(START, "fetch_news")
    # Fan-in: both must complete before analyze runs
    g.add_edge("fetch_market", "analyze")
    g.add_edge("fetch_news", "analyze")
    g.add_edge("analyze", END)

    return g.compile()


research_graph = build_research_graph()


def format_research_result(state: ResearchState) -> str:
    parts: list[str] = []
    if state.get("analysis"):
        parts.append(state["analysis"])

    market = state.get("market_data")
    if market and market.errors:
        parts.append(f"\n⚠️ 일부 시세 수집 실패: {', '.join(market.errors[:3])}")

    news = state.get("news_data")
    if news and news.errors:
        parts.append(f"\n⚠️ 일부 뉴스 수집 실패: {', '.join(news.errors[:3])}")

    return "\n".join(parts) if parts else "데이터를 조회하지 못했습니다."


def _normalize_lang(lang: str) -> Literal["ko", "en"]:
    return "ko" if (lang or "").strip().lower() == "ko" else "en"


async def run_research_detailed(
    query: str, tickers: list[str], lang: str = "ko"
) -> ResearchResult:
    """Run research and return formatted content + structured error info."""
    initial: ResearchState = {
        "query": query,
        "tickers": tickers,
        "lang": _normalize_lang(lang),
        "market_data": None,
        "news_data": None,
        "analysis": None,
        "errors": [],
    }
    result = await research_graph.ainvoke(initial)
    market = result.get("market_data")
    news = result.get("news_data")
    return ResearchResult(
        content=format_research_result(result),
        market_errors=list(market.errors) if market else [],
        news_errors=list(news.errors) if news else [],
    )


async def run_research(
    query: str, tickers: list[str], lang: str = "ko"
) -> str:
    """Backward-compatible wrapper — returns only the formatted string."""
    return (await run_research_detailed(query, tickers, lang)).content
