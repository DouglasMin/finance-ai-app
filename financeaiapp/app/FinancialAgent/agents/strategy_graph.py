"""Strategy monitoring subgraph — evaluates registered strategies against live prices.

Sequential graph: load_strategies → fetch_prices → evaluate → execute.
All pure Python nodes — no LLM. Triggered by EventBridge cron (every 30 min)
via Lambda proxy → POST /strategy-monitor.
"""
import operator
from datetime import datetime, timezone
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from infra.logging_config import get_logger
from schemas.market import MarketQuote

log = get_logger("strategy_graph")


class StrategyState(TypedDict):
    strategies: list[dict]  # loaded from DDB
    quotes: dict[str, Optional[MarketQuote]]  # {symbol: quote}
    triggered: Annotated[list[dict], operator.add]  # results
    errors: Annotated[list[str], operator.add]


# ---------------------------------------------------------------------------
# Node 1: Load enabled strategies from DDB
# ---------------------------------------------------------------------------

async def load_strategies_node(state: StrategyState) -> dict:
    from storage.trading import list_strategies

    strategies = list_strategies()
    enabled = [s for s in strategies if s.enabled]

    if not enabled:
        log.info("strategy.none_enabled")
        return {"strategies": []}

    log.info("strategy.loaded", count=len(enabled))
    return {"strategies": [s.model_dump(mode="json") for s in enabled]}


# ---------------------------------------------------------------------------
# Node 2: Fetch prices for all target symbols (deduplicated)
# ---------------------------------------------------------------------------

async def fetch_prices_node(state: StrategyState) -> dict:
    import asyncio
    from nodes.fetch_market import _fetch_one

    strategies = state.get("strategies") or []
    if not strategies:
        return {"quotes": {}}

    symbols = list({s["target_symbol"] for s in strategies})
    results = await asyncio.gather(
        *[_fetch_one(sym) for sym in symbols], return_exceptions=True
    )

    quotes: dict[str, Optional[MarketQuote]] = {}
    errors: list[str] = []
    for sym, result in zip(symbols, results):
        if isinstance(result, MarketQuote):
            quotes[sym] = result
        elif isinstance(result, Exception):
            errors.append(f"{sym}: {result}")
            quotes[sym] = None
        else:
            quotes[sym] = result

    log.info("strategy.prices_fetched", symbols=len(quotes), errors=len(errors))
    return {"quotes": quotes, "errors": errors}


# ---------------------------------------------------------------------------
# Node 3: Evaluate conditions
# ---------------------------------------------------------------------------

async def evaluate_node(state: StrategyState) -> dict:
    strategies = state.get("strategies") or []
    quotes = state.get("quotes") or {}
    triggered: list[dict] = []

    for s in strategies:
        sym = s["target_symbol"]
        quote = quotes.get(sym)
        if not quote:
            continue

        price = quote.price
        change_pct = quote.change_pct if quote.change_pct is not None else 0
        condition = s["condition_type"]
        threshold = float(s["threshold"])

        met = False
        if condition == "price_above" and price > threshold:
            met = True
        elif condition == "price_below" and price < threshold:
            met = True
        elif condition == "change_pct_above" and change_pct is not None and change_pct > threshold:
            met = True
        elif condition == "change_pct_below" and change_pct is not None and change_pct < -threshold:
            met = True

        if met:
            triggered.append({
                "strategy": s,
                "price": price,
                "change_pct": change_pct,
                "currency": quote.currency,
            })

    log.info("strategy.evaluated", total=len(strategies), triggered=len(triggered))
    return {"triggered": triggered}


# ---------------------------------------------------------------------------
# Node 4: Execute actions for triggered strategies
# ---------------------------------------------------------------------------

async def execute_node(state: StrategyState) -> dict:
    from storage.trading import (
        get_strategy,
        log_strategy_trigger,
        upsert_strategy,
    )
    from tools.trading import _execute_buy, _execute_sell

    triggered = state.get("triggered") or []
    errors: list[str] = []

    for t in triggered:
        s = t["strategy"]
        name = s["name"]
        action = s["action"]
        price = t["price"]
        currency = t["currency"]

        try:
            result_msg = ""

            if action == "alert":
                result_msg = f"조건 충족 알림: {s['target_symbol']} = {price}"
            elif action == "buy" and s.get("quantity"):
                result_msg = await _execute_buy(
                    s["target_symbol"], float(s["quantity"])
                )
            elif action == "sell" and s.get("quantity"):
                result_msg = await _execute_sell(
                    s["target_symbol"], float(s["quantity"])
                )

            success = not result_msg.startswith("❌")

            log_strategy_trigger(name, {
                "action": action,
                "price": price,
                "currency": currency,
                "result": result_msg[:200],
                "success": success,
            })

            # Only increment trigger_count on success
            if success:
                strategy_obj = get_strategy(name)
                if strategy_obj:
                    strategy_obj.last_triggered = datetime.now(timezone.utc)
                    strategy_obj.trigger_count += 1
                    upsert_strategy(strategy_obj)

            log.info("strategy.executed", name=name, action=action,
                     price=price, success=success)

        except Exception as e:
            errors.append(f"{name}: {e}")
            log.error("strategy.execute_failed", name=name, error=str(e))

    return {"errors": errors}


# ---------------------------------------------------------------------------
# Build & compile
# ---------------------------------------------------------------------------

def build_strategy_graph():
    g = StateGraph(StrategyState)
    g.add_node("load_strategies", load_strategies_node)
    g.add_node("fetch_prices", fetch_prices_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("execute", execute_node)

    g.add_edge(START, "load_strategies")
    g.add_edge("load_strategies", "fetch_prices")
    g.add_edge("fetch_prices", "evaluate")
    g.add_edge("evaluate", "execute")
    g.add_edge("execute", END)

    return g.compile()


strategy_graph = build_strategy_graph()


async def run_strategy_monitor() -> dict:
    """Run the strategy monitoring pipeline. Returns summary."""
    initial: StrategyState = {
        "strategies": [],
        "quotes": {},
        "triggered": [],
        "errors": [],
    }
    result = await strategy_graph.ainvoke(initial)
    return {
        "strategies_checked": len(result.get("strategies", [])),
        "triggered": len(result.get("triggered", [])),
        "errors": result.get("errors", []),
    }
