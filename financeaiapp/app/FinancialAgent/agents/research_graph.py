"""Research subgraph — parallel fetch_market ∥ fetch_news → analyze.

This is the core retrieval-and-analysis pipeline. Built with LangGraph
StateGraph, uses fan-out from START to both fetch nodes, then fan-in to
the analyze node. Fetch nodes are pure Python (no LLM); analyze node is
the only LLM call on the retrieval path.
"""
from typing import Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from nodes.analyze import analyze_node
from nodes.fetch_market import fetch_market_node
from nodes.fetch_news import fetch_news_node
from schemas.market import MarketSnapshot
from schemas.news import NewsSnapshot


class ResearchState(TypedDict):
    query: str
    tickers: list[str]
    lang: Literal["ko", "en"]
    market_data: Optional[MarketSnapshot]
    news_data: Optional[NewsSnapshot]
    analysis: Optional[str]
    errors: list[str]


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


async def run_research(
    query: str, tickers: list[str], lang: str = "ko"
) -> str:
    initial: ResearchState = {
        "query": query,
        "tickers": tickers,
        "lang": "ko" if lang == "ko" else "en",
        "market_data": None,
        "news_data": None,
        "analysis": None,
        "errors": [],
    }
    result = await research_graph.ainvoke(initial)
    return format_research_result(result)
