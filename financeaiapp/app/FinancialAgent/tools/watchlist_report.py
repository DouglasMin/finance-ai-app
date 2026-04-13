"""Watchlist batch report tool — analyzes all watchlist items at once."""
from langchain_core.tools import tool

from agents.research_graph import run_research
from infra.logging_config import get_logger
from storage.ddb import query_by_sk_prefix

log = get_logger("watchlist_report")


@tool
async def watchlist_report() -> str:
    """워치리스트의 모든 종목을 한번에 분석합니다.

    시세, 뉴스, 리스크를 종합한 통합 리포트를 생성합니다.
    사용자가 "워치리스트 분석", "전체 종목 리포트" 등을 요청할 때 사용합니다.
    """
    items = query_by_sk_prefix("WATCH#")
    if not items:
        return "워치리스트가 비어 있습니다. 먼저 종목을 추가해 주세요."

    tickers = [item["symbol"] for item in items if "symbol" in item]
    if not tickers:
        return "워치리스트에 유효한 종목이 없습니다."

    try:
        return await run_research(
            query=f"워치리스트 전체 종목 통합 분석: {', '.join(tickers)}",
            tickers=tickers,
            lang="ko",
        )
    except Exception as e:
        log.error("watchlist_report.failed", error=str(e), exc_info=True)
        return "워치리스트 분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
