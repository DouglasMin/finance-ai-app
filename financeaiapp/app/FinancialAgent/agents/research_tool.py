"""Research tool — exposes the LangGraph research subgraph as a LangChain tool."""
from langchain_core.tools import tool

from agents.research_graph import run_research


@tool
async def research(
    query: str,
    tickers: list[str] | None = None,
    lang: str = "ko",
) -> str:
    """금융 시장 리서치 도구. 시세와 뉴스를 병렬로 수집해 종합 분석을 반환합니다.

    Args:
        query: 사용자의 질문 (예: "BTC 시세 어때", "반도체 전망")
        tickers: 분석할 종목 리스트. 크립토는 BTC/ETH, 미국 주식은 AAPL/TSLA,
                 한국 주식은 6자리 종목코드 (예: 005930), 환율은 USD/KRW 형식.
        lang: 응답 언어 ("ko" 또는 "en", 기본 ko)

    Returns:
        구조화된 분석 텍스트. 시세 + 뉴스 + 판단 + 리스크.
    """
    return await run_research(query, tickers or [], lang)
