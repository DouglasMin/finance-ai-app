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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from starlette.requests import Request
from starlette.responses import JSONResponse

from agents.research_graph import run_research_detailed
from infra.logging_config import correlation_id_var, get_logger
from schemas.briefing import BriefingRecord
from storage.ddb import put_item, query_by_sk_prefix

log = get_logger("briefing_handler")


def _kst_date() -> str:
    """Return current date in KST as YYYY-MM-DD."""
    kst = datetime.now(timezone.utc) + timedelta(hours=9)
    return kst.strftime("%Y-%m-%d")


_briefing_prompt: str | None = None
_briefing_prompt_path = (
    Path(__file__).resolve().parent.parent / "prompts" / "briefing.md"
)


def _load_briefing_prompt() -> str:
    global _briefing_prompt
    if _briefing_prompt is None:
        _briefing_prompt = _briefing_prompt_path.read_text(encoding="utf-8")
    return _briefing_prompt


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

        # Stage 3: run research (returns content + structured error info)
        query = _build_briefing_query(time_of_day, tickers)
        research = await run_research_detailed(
            query=query, tickers=tickers, lang="ko"
        )
        content = research.content

        duration_ms = int(
            (datetime.now(timezone.utc) - start).total_seconds() * 1000
        )

        # Stage 4: decide status from structured errors (not text scraping)
        status: BriefingRecord.__annotations__["status"] = "success"
        errors: list[str] = []
        if research.has_errors:
            status = "partial"
            errors.extend(f"market: {e}" for e in research.market_errors)
            errors.extend(f"news: {e}" for e in research.news_errors)

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

        # Stage 5: save PnL snapshot if portfolio exists
        try:
            from nodes.fetch_market import _fetch_one
            from storage.trading import (
                get_portfolio as _get_pf,
                list_positions as _list_pos,
                save_pnl_snapshot,
            )
            from schemas.trading import PnlSnapshot
            from tools.trading import _convert_price

            pf = _get_pf()
            if pf:
                positions = _list_pos()
                total_market = 0.0
                total_unrealized = 0.0
                priced_count = 0
                failed_symbols: list[str] = []
                for pos in positions:
                    try:
                        quote = await _fetch_one(pos.symbol)
                        if quote:
                            price_in_pf = quote.price
                            if quote.currency != pf.currency:
                                converted = await _convert_price(
                                    quote.price, quote.currency, pf.currency
                                )
                                if converted:
                                    price_in_pf = converted
                            mkt = price_in_pf * pos.quantity
                            total_market += mkt
                            total_unrealized += mkt - (pos.avg_cost * pos.quantity)
                            priced_count += 1
                        else:
                            failed_symbols.append(pos.symbol)
                    except Exception as exc:
                        failed_symbols.append(pos.symbol)
                        log.warning("pnl_snapshot.position_failed",
                                    symbol=pos.symbol, error=str(exc))
                # Only save if all positions were priced (no partial data)
                if not failed_symbols:
                    save_pnl_snapshot(PnlSnapshot(
                        date=date_str,
                        total_value=pf.cash_balance + total_market,
                        cash=pf.cash_balance,
                        unrealized_pnl=total_unrealized,
                        realized_pnl=pf.realized_pnl,
                        positions_count=priced_count,
                    ))
                    log.info("pnl_snapshot.saved", date=date_str)
                else:
                    log.warning("pnl_snapshot.skipped",
                                failed=failed_symbols, date=date_str)
        except Exception as e:
            log.warning("pnl_snapshot.failed", error=str(e))

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
