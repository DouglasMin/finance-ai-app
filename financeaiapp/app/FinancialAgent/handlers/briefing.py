"""Briefing generation handler — invoked by Lambda proxy on EventBridge cron.

Flow:
1. Lambda proxy hits POST /briefing with {"time_of_day": "AM"|"PM"}
2. This handler:
   - Marks briefing as pending in DDB
   - Loads user's watchlist
   - Runs research subgraph with briefing-specific prompt
   - Updates DDB with final content + status (success/partial/failed)
3. UI polls DDB (via orchestrator tool) to display briefings
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from starlette.requests import Request
from starlette.responses import JSONResponse

from agents.research_graph import run_research
from infra.logging_config import correlation_id_var, get_logger
from schemas.briefing import BriefingRecord
from storage.ddb import put_item, query_by_sk_prefix

log = get_logger("briefing_handler")


def _kst_date() -> str:
    """Return current date in KST as YYYY-MM-DD."""
    kst = datetime.now(timezone.utc) + timedelta(hours=9)
    return kst.strftime("%Y-%m-%d")


def _load_briefing_prompt() -> str:
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "prompts", "briefing.md"
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def _build_briefing_query(
    time_of_day: Literal["AM", "PM"], tickers: list[str]
) -> str:
    period = "아침" if time_of_day == "AM" else "저녁"
    date_str = _kst_date()
    prompt_template = _load_briefing_prompt()
    return (
        f"{prompt_template}\n\n"
        f"## 요청\n"
        f"오늘({date_str}) {period} 브리핑을 작성해주세요.\n"
        f"관심 종목: {', '.join(tickers)}\n"
    )


async def run_briefing(
    time_of_day: Literal["AM", "PM"],
    correlation_id: str | None = None,
) -> dict:
    """Core briefing flow — reusable from both HTTP and entrypoint dispatch.

    Writes progress to DDB (pending → success/partial/failed) and returns a
    result dict. Never raises — failures are serialized into the result.
    """
    if time_of_day not in ("AM", "PM"):
        return {"status": "failed", "error": f"Invalid time_of_day: {time_of_day}"}

    correlation_id_var.set(
        correlation_id or f"briefing-{int(datetime.now().timestamp())}"
    )

    date_str = _kst_date()
    sk = f"BRIEF#{date_str}-{time_of_day}"
    start = datetime.now(timezone.utc)
    log.info("briefing.start", date=date_str, time=time_of_day)

    # Stage 1: pending marker
    put_item(
        sk,
        {
            "date": date_str,
            "time_of_day": time_of_day,
            "status": "pending",
            "content": "",
            "generated_at": start.isoformat(),
        },
    )

    try:
        # Stage 2: load watchlist
        watch_items = query_by_sk_prefix("WATCH#")
        tickers = [item["symbol"] for item in watch_items if "symbol" in item]

        if not tickers:
            put_item(
                sk,
                {
                    "date": date_str,
                    "time_of_day": time_of_day,
                    "status": "failed",
                    "content": "관심 종목이 없어 브리핑을 생성할 수 없습니다.",
                    "tickers_covered": [],
                    "generated_at": start.isoformat(),
                    "duration_ms": 0,
                    "errors": ["empty_watchlist"],
                },
            )
            log.warning("briefing.empty_watchlist")
            return {"status": "failed", "reason": "empty_watchlist"}

        # Stage 3: run research
        query = _build_briefing_query(time_of_day, tickers)
        content = await run_research(query=query, tickers=tickers, lang="ko")

        duration_ms = int(
            (datetime.now(timezone.utc) - start).total_seconds() * 1000
        )

        # Stage 4: decide status — partial if content mentions data gaps
        status: BriefingRecord.__annotations__["status"] = "success"
        errors: list[str] = []
        if "데이터 누락" in content or "데이터 부족" in content or "⚠️" in content:
            status = "partial"
            errors.append("data_gaps_detected_in_content")

        record = BriefingRecord(
            date=date_str,
            time_of_day=time_of_day,
            status=status,
            content=content,
            tickers_covered=tickers,
            generated_at=start,
            duration_ms=duration_ms,
            errors=errors,
        )

        put_item(
            sk,
            {
                "date": record.date,
                "time_of_day": record.time_of_day,
                "status": record.status,
                "content": record.content,
                "tickers_covered": record.tickers_covered,
                "generated_at": record.generated_at.isoformat(),
                "duration_ms": record.duration_ms,
                "errors": record.errors,
            },
        )

        log.info(
            "briefing.complete",
            sk=sk,
            status=status,
            duration_ms=duration_ms,
            tickers=len(tickers),
        )
        return {
            "status": status,
            "briefing_sk": sk,
            "duration_ms": duration_ms,
            "tickers_covered": tickers,
        }

    except Exception as e:
        log.exception("briefing.failed")
        duration_ms = int(
            (datetime.now(timezone.utc) - start).total_seconds() * 1000
        )
        put_item(
            sk,
            {
                "date": date_str,
                "time_of_day": time_of_day,
                "status": "failed",
                "content": f"브리핑 생성 실패: {e}",
                "tickers_covered": [],
                "generated_at": start.isoformat(),
                "duration_ms": duration_ms,
                "errors": [str(e)],
            },
        )
        return {"status": "failed", "error": str(e)}


async def generate_briefing(request: Request) -> JSONResponse:
    """POST /briefing — HTTP wrapper around run_briefing for local dev."""
    body = await request.json()
    time_of_day = body.get("time_of_day", "AM")
    correlation_id = body.get("correlation_id")
    result = await run_briefing(time_of_day, correlation_id)
    status_code = 500 if result.get("status") == "failed" and "error" in result else 200
    return JSONResponse(result, status_code=status_code)
