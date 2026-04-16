"""Financial Agent — AgentCore Runtime entrypoint.

Top-level orchestrator invocation with SSE streaming. Each yielded dict
is wrapped as `data: {json}\n\n` by AgentCore's _convert_to_sse.
"""
import os
import re
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_core.messages import HumanMessage

from agents.orchestrator import get_orchestrator
from handlers.briefing import generate_briefing, run_briefing
from handlers.watchlist import get_watchlist_items, list_watchlist
from infra.llm import get_provider
from infra.logging_config import correlation_id_var, get_logger, setup_logging
from infra.secrets import get_secret
from storage.ddb import put_item
from tools.sessions import upsert_session

setup_logging()
log = get_logger("main")

# langchain/langsmith reads LANGSMITH_API_KEY directly from os.environ,
# so we must inject it from Secrets Manager before any traced call runs.
# Non-sensitive flags (LANGCHAIN_TRACING_V2, LANGSMITH_TRACING, LANGSMITH_PROJECT)
# are set in the Dockerfile.
_tracing_enabled = (
    os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    or os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
)
if _tracing_enabled:
    _ls_key = get_secret("LANGSMITH_API_KEY")
    if _ls_key:
        os.environ.setdefault("LANGSMITH_API_KEY", _ls_key)
        os.environ.setdefault("LANGCHAIN_API_KEY", _ls_key)
        log.info("langsmith.enabled", project=os.environ.get("LANGSMITH_PROJECT"))
    else:
        log.warning("langsmith.key.missing", reason="not in Secrets Manager")

app = BedrockAgentCoreApp()

# Custom route: POST /briefing — called by Lambda proxy from EventBridge cron
app.add_route("/briefing", generate_briefing, methods=["POST"])

# Custom route: GET /watchlist — direct JSON endpoint for the UI side panel
app.add_route("/watchlist", list_watchlist, methods=["GET"])


@app.entrypoint
async def invoke(payload, context):
    """Primary entrypoint — dispatches on `action` field.

    Supported actions (all work in dev + prod via InvokeAgentRuntimeCommand):
      - "chat" (default): streams orchestrator events as SSE
      - "briefing": runs the daily briefing flow and yields one result event
      - "list_watchlist": returns the enriched watchlist as one event

    Non-chat actions are one-shot and yield a single data event + complete.
    """
    action = payload.get("action", "chat")
    correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
    correlation_id_var.set(correlation_id)

    log.info("invoke.start", action=action)

    if action == "list_watchlist":
        items = await get_watchlist_items()
        yield {"event": "watchlist", "items": items}
        yield {"event": "complete"}
        return

    if action == "add_watchlist":
        from nodes.fetch_market import _fetch_one
        from tools.watchlist import add_watchlist_item
        symbol = (payload.get("symbol") or "").strip()
        if not symbol:
            yield {"event": "error", "message": "Missing symbol"}
            return
        # Validate by fetching a live quote — reject if no data exists
        quote = await _fetch_one(symbol.upper())
        if quote is None:
            yield {
                "event": "error",
                "code": "symbol_not_found",
                "message": f"'{symbol.upper()}'에 대한 시세를 찾을 수 없습니다. 종목 심볼을 확인해 주세요.",
            }
            return
        sym, _cat = await add_watchlist_item(
            symbol, payload.get("category") or ""
        )
        yield {"event": "watchlist_updated", "action": "add", "symbol": sym}
        yield {"event": "complete"}
        return

    if action == "remove_watchlist":
        from tools.watchlist import remove_watchlist_item
        symbol = (payload.get("symbol") or "").strip()
        if not symbol:
            yield {"event": "error", "message": "Missing symbol"}
            return
        sym = remove_watchlist_item(symbol)
        yield {"event": "watchlist_updated", "action": "remove", "symbol": sym}
        yield {"event": "complete"}
        return

    if action == "list_briefings":
        from storage.ddb import query_by_sk_prefix
        items = query_by_sk_prefix("BRIEF#", limit=10, ascending=False)
        briefings = [
            {
                "date": item.get("date", ""),
                "time_of_day": item.get("time_of_day", ""),
                "status": item.get("status", ""),
                "tickers_covered": item.get("tickers_covered", []),
                "content": item.get("content", ""),
            }
            for item in items
        ]
        yield {"event": "briefings", "items": briefings}
        yield {"event": "complete"}
        return

    if action == "get_llm_provider":
        provider = get_provider()
        yield {"event": "llm_provider", "provider": provider}
        yield {"event": "complete"}
        return

    if action == "set_llm_provider":
        new_provider = payload.get("provider", "").lower()
        if new_provider not in ("openai", "bedrock"):
            yield {"event": "error", "message": f"Invalid provider: {new_provider}. Use 'openai' or 'bedrock'."}
            return
        from datetime import datetime, timezone
        put_item("PREF#llm_provider", {
            "value": new_provider,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        log.info("llm_provider.changed", provider=new_provider)
        yield {"event": "llm_provider", "provider": new_provider}
        yield {"event": "complete"}
        return

    if action == "briefing":
        time_of_day = payload.get("time_of_day", "AM")
        result = await run_briefing(time_of_day, correlation_id)
        yield {"event": "briefing_result", **result}
        yield {"event": "complete"}
        return

    if action == "strategy_monitor":
        from agents.strategy_graph import run_strategy_monitor
        result = await run_strategy_monitor()
        yield {"event": "strategy_monitor_result", **result}
        yield {"event": "complete"}
        return

    # ----- Phase 2: Paper Trading direct actions -----
    if action == "get_portfolio":
        from storage.trading import get_portfolio as _get_pf, list_positions as _list_pos
        pf = _get_pf()
        if not pf:
            yield {"event": "portfolio", "portfolio": None, "positions": []}
        else:
            positions = _list_pos()
            yield {
                "event": "portfolio",
                "portfolio": pf.model_dump(mode="json"),
                "positions": [p.model_dump(mode="json") for p in positions],
            }
        yield {"event": "complete"}
        return

    if action == "init_portfolio":
        from datetime import datetime as _dt, timezone as _tz
        from schemas.trading import Portfolio
        from storage.trading import upsert_portfolio
        from infra.formatting import format_price as _fp
        capital = float(payload.get("initial_capital", 10000))
        currency = str(payload.get("currency", "USD"))
        if currency not in ("USD", "KRW"):
            yield {"event": "error", "message": f"지원하지 않는 통화: {currency}"}
            return
        if capital <= 0:
            yield {"event": "error", "message": "초기 자금은 0보다 커야 합니다."}
            return
        pf = Portfolio(
            initial_capital=capital,
            cash_balance=capital,
            realized_pnl=0.0,
            currency=currency,
            created_at=_dt.now(_tz.utc),
        )
        upsert_portfolio(pf)
        yield {
            "event": "portfolio_updated",
            "message": f"✅ 포트폴리오 생성 완료 — {_fp(capital, currency)}",
        }
        yield {"event": "complete"}
        return

    if action == "direct_buy":
        from nodes.fetch_market import _fetch_one as _fq
        from tools.sources.classifier import classify_ticker as _ct
        from schemas.trading import Order, Position
        from storage.trading import (
            get_portfolio as _gp, upsert_portfolio as _up,
            get_position as _gpos, upsert_position as _upos,
            create_order as _co, new_order_id as _nid,
        )
        from infra.formatting import format_price as _fp
        from datetime import datetime as _dt, timezone as _tz

        symbol = (payload.get("symbol") or "").strip().upper()
        quantity = float(payload.get("quantity", 0))
        if not symbol or quantity <= 0:
            yield {"event": "error", "message": "symbol과 quantity(>0)가 필요합니다."}
            return
        portfolio = _gp()
        if not portfolio:
            yield {"event": "error", "message": "포트폴리오가 없습니다. 먼저 생성해 주세요."}
            return
        category = await _ct(symbol)
        quote = await _fq(symbol)
        if not quote:
            yield {"event": "error", "message": f"'{symbol}' 시세를 조회할 수 없습니다."}
            return
        if quote.currency != portfolio.currency:
            yield {"event": "error", "message": f"통화 불일치: 포트폴리오({portfolio.currency}) ≠ 종목({quote.currency})"}
            return
        total_cost = quote.price * quantity
        if total_cost > portfolio.cash_balance:
            yield {"event": "error", "message": f"잔고 부족: 필요 {_fp(total_cost, quote.currency)}, 잔고 {_fp(portfolio.cash_balance, portfolio.currency)}"}
            return
        now = _dt.now(_tz.utc)
        portfolio.cash_balance -= total_cost
        _up(portfolio)
        existing = _gpos(symbol)
        if existing:
            new_qty = existing.quantity + quantity
            existing.avg_cost = (existing.avg_cost * existing.quantity + quote.price * quantity) / new_qty
            existing.quantity = new_qty
            existing.updated_at = now
            _upos(existing)
        else:
            _upos(Position(symbol=symbol, category=category, quantity=quantity, avg_cost=quote.price, currency=quote.currency, opened_at=now, updated_at=now))
        _co(Order(order_id=_nid(), symbol=symbol, side="buy", quantity=quantity, price=quote.price, total_cost=total_cost, currency=quote.currency, created_at=now))
        yield {"event": "trade_result", "message": f"✅ {symbol} {quantity:,.4g}개 매수 @ {_fp(quote.price, quote.currency)}"}
        yield {"event": "portfolio_update"}
        yield {"event": "complete"}
        return

    if action == "direct_sell":
        from nodes.fetch_market import _fetch_one as _fq
        from schemas.trading import Order
        from storage.trading import (
            get_portfolio as _gp, upsert_portfolio as _up,
            get_position as _gpos, upsert_position as _upos,
            delete_position as _dp,
            create_order as _co, new_order_id as _nid,
        )
        from infra.formatting import format_price as _fp
        from datetime import datetime as _dt, timezone as _tz

        symbol = (payload.get("symbol") or "").strip().upper()
        quantity = float(payload.get("quantity", 0))
        if not symbol:
            yield {"event": "error", "message": "symbol이 필요합니다."}
            return
        portfolio = _gp()
        if not portfolio:
            yield {"event": "error", "message": "포트폴리오가 없습니다."}
            return
        position = _gpos(symbol)
        if not position:
            yield {"event": "error", "message": f"'{symbol}' 보유 포지션이 없습니다."}
            return
        if quantity < 0:
            yield {"event": "error", "message": "수량은 0 이상이어야 합니다."}
            return
        sell_qty = quantity if quantity > 0 else position.quantity
        if sell_qty > position.quantity + 1e-9:
            yield {"event": "error", "message": f"보유 수량 초과: 보유 {position.quantity:,.4g}, 요청 {sell_qty:,.4g}"}
            return
        sell_qty = min(sell_qty, position.quantity)
        quote = await _fq(symbol)
        if not quote:
            yield {"event": "error", "message": f"'{symbol}' 시세를 조회할 수 없습니다."}
            return
        proceeds = quote.price * sell_qty
        realized = (quote.price - position.avg_cost) * sell_qty
        now = _dt.now(_tz.utc)
        portfolio.cash_balance += proceeds
        portfolio.realized_pnl += realized
        _up(portfolio)
        remaining = max(0.0, position.quantity - sell_qty)
        if remaining > 1e-9:
            position.quantity = remaining
            position.updated_at = now
            _upos(position)
        else:
            _dp(symbol)
        _co(Order(order_id=_nid(), symbol=symbol, side="sell", quantity=sell_qty, price=quote.price, total_cost=proceeds, currency=quote.currency, created_at=now))
        pnl_emoji = "🔺" if realized >= 0 else "🔻"
        yield {"event": "trade_result", "message": f"✅ {symbol} {sell_qty:,.4g}개 매도 @ {_fp(quote.price, quote.currency)} | {pnl_emoji} {_fp(realized, quote.currency)}"}
        yield {"event": "portfolio_update"}
        yield {"event": "complete"}
        return

    if action == "get_orders":
        from storage.trading import list_orders as _list_ord
        limit = min(max(int(payload.get("limit", 20)), 1), 50)
        orders = _list_ord(limit=limit)
        yield {
            "event": "orders",
            "items": [o.model_dump(mode="json") for o in orders],
        }
        yield {"event": "complete"}
        return

    if action != "chat":
        yield {"event": "error", "message": f"Unknown action: {action}"}
        return

    session_id = payload.get("session_id") or f"sess-{uuid.uuid4().hex[:12]}"
    message = payload.get("message") or ""

    if not message.strip():
        yield {"event": "error", "message": "Empty message"}
        return

    orchestrator = get_orchestrator()

    yield {
        "event": "session_start",
        "session_id": session_id,
        "correlation_id": correlation_id,
    }

    thread_config = {
        "configurable": {
            "thread_id": session_id,
            "actor_id": "user-me",
        },
        "recursion_limit": 15,
    }
    input_payload = {"messages": [HumanMessage(content=message)]}

    pending_chart: str | None = None

    try:
        # Stream updates mode: emits per-node deltas as the graph runs
        async for chunk in orchestrator.astream(
            input_payload, config=thread_config, stream_mode="updates"
        ):
            for node_name, node_output in chunk.items():
                if not isinstance(node_output, dict) or "messages" not in node_output:
                    continue
                for msg in node_output["messages"]:
                    msg_type = getattr(msg, "type", None)
                    # Tool call events (AI message with tool_calls)
                    if msg_type == "ai" and getattr(msg, "tool_calls", None):
                        for tc in msg.tool_calls:
                            yield {
                                "event": "tool_call",
                                "tool": tc.get("name"),
                                "args": tc.get("args", {}),
                            }
                    # Tool result events
                    elif msg_type == "tool":
                        tool_name = getattr(msg, "name", "")
                        content = getattr(msg, "content", "")
                        if not isinstance(content, str):
                            content = str(content)
                        # Extract [CHART] block before truncating
                        if tool_name == "compare_tickers":
                            chart_match = re.search(
                                r"\[CHART\]\n[\s\S]*?\n\[/CHART\]", content
                            )
                            if chart_match:
                                pending_chart = chart_match.group(0)
                        yield {
                            "event": "tool_result",
                            "tool": tool_name,
                            "content": content[:1000],
                        }
                        # Auto-emit portfolio_update when trading tools complete
                        if tool_name in ("buy", "buy_amount", "sell"):
                            yield {"event": "portfolio_update"}
                        # Auto-emit news links from research results
                        if tool_name == "research":
                            links = re.findall(
                                r"\[([^\]]+)\]\((https?://[^\)]+)\)",
                                content,
                            )
                            if links:
                                yield {
                                    "event": "news_links",
                                    "items": [
                                        {"title": t, "url": u}
                                        for t, u in links
                                        if "원문 보기" not in t
                                    ],
                                }
                    # Assistant message (final or streaming segment)
                    elif msg_type == "ai":
                        content = getattr(msg, "content", "")
                        if isinstance(content, str) and content:
                            # Append pending chart only if LLM didn't already
                            # include the [CHART] block itself (avoid duplicate)
                            if pending_chart and "[CHART]" not in content:
                                content += "\n\n" + pending_chart
                            pending_chart = None
                            yield {"event": "assistant", "content": content}

        # Update session metadata (DDB) — truncate title
        title = message[:50]
        try:
            upsert_session(session_id, title=title, increment_message=True)
        except Exception as e:
            log.warning("session.upsert.failed", error=str(e))

        yield {"event": "complete", "session_id": session_id}
        log.info("invoke.complete", session_id=session_id)
    except Exception as e:
        log.exception("invoke.failed")
        yield {"event": "error", "message": str(e)}


if __name__ == "__main__":
    app.run()
