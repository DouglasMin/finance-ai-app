"""Paper trading tools — virtual portfolio management for the orchestrator.

All trades execute at current market price (from OKX/AV/pykrx/Frankfurter).
No real money, no exchange API — prices are fetched the same way as the
research tool, then recorded in DynamoDB.

Concurrency note: single-user system with serial agent execution. DDB writes
are not atomic (no conditional expressions) but race conditions are not
practical in this deployment model.
"""
import asyncio
import json
from datetime import datetime, timezone

from langchain_core.tools import tool
from pydantic import ValidationError

from infra.formatting import format_price
from infra.logging_config import get_logger
from nodes.fetch_market import _fetch_one
from schemas.trading import Order, Portfolio, Position
from storage.trading import (
    create_order,
    get_portfolio,
    get_position,
    list_orders,
    list_pnl_snapshots,
    list_positions,
    new_order_id,
    upsert_portfolio,
    upsert_position,
    delete_position,
)
from tools.sources.classifier import classify_ticker
from tools.sources.frankfurter import get_fx_rate

log = get_logger("trading_tools")


async def _convert_price(
    price: float, from_currency: str, to_currency: str
) -> float | None:
    """Convert price between currencies via Frankfurter. Returns None on failure."""
    if from_currency == to_currency:
        return price
    rate = await get_fx_rate(from_currency, to_currency)
    if rate is None:
        return None
    return price * rate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_quotes(symbols: list[str]) -> dict:
    """Fetch quotes in parallel. Returns {symbol: MarketQuote | None}."""
    results = await asyncio.gather(
        *[_fetch_one(s) for s in symbols], return_exceptions=True
    )
    return {
        sym: (q if not isinstance(q, Exception) else None)
        for sym, q in zip(symbols, results)
    }


async def _quote_price_in_currency(
    quote, target_currency: str
) -> float | None:
    """Convert a quote's price to target currency. Returns None on FX failure."""
    if quote is None:
        return None
    if quote.currency == target_currency:
        return quote.price
    return await _convert_price(quote.price, quote.currency, target_currency)


# ---------------------------------------------------------------------------
# Price lookup
# ---------------------------------------------------------------------------

@tool
async def get_price(symbol: str) -> str:
    """종목의 현재 시세를 빠르게 조회합니다. 뉴스/분석 없이 가격만 반환합니다.

    "BTC 현재가?", "삼성전자 시세", "ETH 얼마야" 같은 단순 시세 질문에 사용합니다.
    포트폴리오가 있으면 포트폴리오 통화 기준 환산가도 함께 반환합니다.
    "500만원어치면 몇 개?" 같은 금액↔수량 환산 질문에도 이 결과를 사용하세요.
    직접 계산하지 마세요.

    Args:
        symbol: 종목 심볼 (BTC, AAPL, 005930 등)
    """
    sym = symbol.upper().strip()
    quote = await _fetch_one(sym)
    if not quote:
        return f"❌ {sym} 시세를 조회할 수 없습니다."

    change_str = ""
    if quote.change_pct is not None:
        emoji = "🔺" if quote.change_pct >= 0 else "🔻"
        change_str = f" {emoji} {quote.change_pct:+.2f}%"

    range_str = ""
    if quote.high is not None and quote.low is not None:
        range_str = (
            f"\n고가: {format_price(quote.high, quote.currency)} / "
            f"저가: {format_price(quote.low, quote.currency)}"
        )

    lines = [
        f"**{sym}** {format_price(quote.price, quote.currency)}{change_str}",
    ]
    if range_str:
        lines.append(range_str)

    # 포트폴리오 통화와 다르면 환산가 + 금액별 수량 참고표 추가
    portfolio = get_portfolio()
    if portfolio and quote.currency != portfolio.currency:
        converted = await _convert_price(
            quote.price, quote.currency, portfolio.currency
        )
        if converted:
            lines.append(
                f"\n포트폴리오 통화 환산: {format_price(converted, portfolio.currency)}/개"
            )
            for amt in [1_000_000, 5_000_000, 10_000_000]:
                qty = amt / converted
                lines.append(
                    f"  {format_price(amt, portfolio.currency)}어치 ≈ {qty:,.6g}개"
                )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Portfolio init / view
# ---------------------------------------------------------------------------

@tool
def init_portfolio(initial_capital: float, currency: str = "USD") -> str:
    """가상 포트폴리오를 초기화합니다. 기존 포트폴리오가 있으면 덮어씁니다.

    Args:
        initial_capital: 시작 자금 (예: 10000)
        currency: 기본 통화 (USD 또는 KRW)
    """
    if currency not in ("USD", "KRW"):
        return f"❌ 지원하지 않는 통화입니다: {currency}. USD 또는 KRW만 가능합니다."

    try:
        portfolio = Portfolio(
            initial_capital=initial_capital,
            cash_balance=initial_capital,
            realized_pnl=0.0,
            currency=currency,
            created_at=datetime.now(timezone.utc),
        )
    except ValidationError:
        return "❌ 초기 자금은 0보다 커야 합니다."

    upsert_portfolio(portfolio)
    return (
        f"✅ 가상 포트폴리오 생성 완료\n"
        f"초기 자금: {format_price(initial_capital, currency)}\n"
        f"통화: {currency}"
    )


@tool
async def get_portfolio_summary() -> str:
    """현재 포트폴리오 요약을 반환합니다 — 잔고, 보유 종목 수, 총 평가액, PnL."""
    portfolio = get_portfolio()
    if not portfolio:
        return "포트폴리오가 없습니다. `init_portfolio`로 먼저 생성해 주세요."

    positions = list_positions()
    total_unrealized = 0.0
    total_market_value = 0.0
    failed_symbols: list[str] = []

    quotes = await _fetch_quotes([p.symbol for p in positions])
    for pos in positions:
        quote = quotes.get(pos.symbol)
        cur_price = await _quote_price_in_currency(
            quote, portfolio.currency
        ) if quote else None
        if cur_price is not None:
            market_val = cur_price * pos.quantity
            cost_val = pos.avg_cost * pos.quantity
            total_market_value += market_val
            total_unrealized += market_val - cost_val
        else:
            failed_symbols.append(pos.symbol)

    total_value = portfolio.cash_balance + total_market_value
    total_pnl = portfolio.realized_pnl + total_unrealized

    pnl_emoji = "🔺" if total_pnl >= 0 else "🔻"
    pnl_pct = (total_pnl / portfolio.initial_capital * 100) if portfolio.initial_capital else 0

    lines = [
        "## 📊 포트폴리오 요약",
        f"- 총 평가: {format_price(total_value, portfolio.currency)}",
        f"- 현금: {format_price(portfolio.cash_balance, portfolio.currency)}",
        f"- 보유 종목: {len(positions)}개 ({format_price(total_market_value, portfolio.currency)})",
        f"- 실현 손익: {format_price(portfolio.realized_pnl, portfolio.currency)}",
        f"- 미실현 손익: {format_price(total_unrealized, portfolio.currency)}",
        f"- 전체 PnL: {pnl_emoji} {format_price(total_pnl, portfolio.currency)} ({pnl_pct:+.2f}%)",
    ]
    if failed_symbols:
        lines.append(f"\n⚠️ 시세 조회 실패: {', '.join(failed_symbols)} (해당 종목 제외)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

@tool
async def get_positions_list() -> str:
    """보유 중인 모든 포지션을 현재 시세와 함께 반환합니다."""
    portfolio = get_portfolio()
    if not portfolio:
        return "포트폴리오가 없습니다."

    positions = list_positions()
    if not positions:
        return "보유 중인 포지션이 없습니다."

    quotes = await _fetch_quotes([p.symbol for p in positions])

    lines = ["## 💼 보유 포지션\n"]
    lines.append("| 종목 | 수량 | 평단가 | 현재가 | 손익 |")
    lines.append("|------|------|--------|--------|------|")

    for pos in positions:
        quote = quotes.get(pos.symbol)
        cur_price = await _quote_price_in_currency(
            quote, portfolio.currency
        ) if quote else None
        if cur_price is not None:
            pnl = (cur_price - pos.avg_cost) * pos.quantity
            pnl_pct = ((cur_price / pos.avg_cost - 1) * 100) if pos.avg_cost else 0
        else:
            pnl = 0
            pnl_pct = 0
        emoji = "🔺" if pnl >= 0 else "🔻"
        price_str = format_price(cur_price, portfolio.currency) if cur_price else "N/A"

        lines.append(
            f"| {pos.symbol} | {pos.quantity:,.4g} "
            f"| {format_price(pos.avg_cost, portfolio.currency)} "
            f"| {price_str} "
            f"| {emoji} {pnl_pct:+.2f}% |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Buy / Sell
# ---------------------------------------------------------------------------

async def _execute_buy(sym: str, quantity: float) -> str:
    """Internal buy logic — shared by buy (quantity) and buy_amount (amount)."""
    portfolio = get_portfolio()
    if not portfolio:
        return "❌ 포트폴리오가 없습니다. 먼저 `init_portfolio`로 생성해 주세요."

    category = await classify_ticker(sym)
    quote = await _fetch_one(sym)
    if not quote:
        return f"❌ {sym} 시세를 조회할 수 없습니다."

    # FX: convert quote price to portfolio currency
    price_in_pf = quote.price
    fx_info = ""
    if quote.currency != portfolio.currency:
        converted = await _convert_price(quote.price, quote.currency, portfolio.currency)
        if converted is None:
            return f"❌ 환율 조회 실패: {quote.currency} → {portfolio.currency}"
        price_in_pf = converted
        fx_info = f"\n환율: 1 {quote.currency} = {format_price(price_in_pf / quote.price, portfolio.currency)}"

    total_cost = price_in_pf * quantity
    if total_cost > portfolio.cash_balance:
        return (
            f"❌ 잔고 부족\n"
            f"필요: {format_price(total_cost, portfolio.currency)}\n"
            f"잔고: {format_price(portfolio.cash_balance, portfolio.currency)}"
        )

    now = datetime.now(timezone.utc)
    portfolio.cash_balance -= total_cost
    upsert_portfolio(portfolio)

    existing = get_position(sym)
    if existing:
        new_qty = existing.quantity + quantity
        existing.avg_cost = (existing.avg_cost * existing.quantity + price_in_pf * quantity) / new_qty
        existing.quantity = new_qty
        existing.updated_at = now
        upsert_position(existing)
    else:
        upsert_position(Position(
            symbol=sym, category=category, quantity=quantity,
            avg_cost=price_in_pf, currency=portfolio.currency,
            opened_at=now, updated_at=now,
        ))

    create_order(Order(
        order_id=new_order_id(), symbol=sym, side="buy",
        quantity=quantity, price=price_in_pf, total_cost=total_cost,
        currency=portfolio.currency, created_at=now,
    ))
    log.info("trade.buy", symbol=sym, qty=quantity, price=price_in_pf)

    return (
        f"✅ **{sym}** {quantity:,.6g}개 매수 완료\n"
        f"체결가: {format_price(price_in_pf, portfolio.currency)}"
        f" (원가: {format_price(quote.price, quote.currency)}){fx_info}\n"
        f"총액: {format_price(total_cost, portfolio.currency)}\n"
        f"잔고: {format_price(portfolio.cash_balance, portfolio.currency)}"
    )


@tool
async def buy(symbol: str, quantity: float) -> str:
    """종목을 수량 기준으로 가상 매수합니다. "BTC 0.1개 사줘" 같은 요청에 사용.

    Args:
        symbol: 종목 심볼 (BTC, AAPL, 005930 등)
        quantity: 매수 수량 (예: 0.1)
    """
    if quantity <= 0:
        return "❌ 수량은 0보다 커야 합니다."
    return await _execute_buy(symbol.upper().strip(), quantity)


@tool
async def buy_amount(symbol: str, amount: float, currency: str) -> str:
    """종목을 금액 기준으로 가상 매수합니다. "BTC 500만원어치 사줘" 같은 요청에 사용.
    현재가로 수량을 자동 계산합니다.

    Args:
        symbol: 종목 심볼 (BTC, AAPL, 005930 등)
        amount: 매수 금액 (예: 5000000)
        currency: 금액의 통화. "KRW" = 한화/원, "USD" = 달러.
    """
    if amount <= 0:
        return "❌ 금액은 0보다 커야 합니다."

    sym = symbol.upper().strip()
    portfolio = get_portfolio()
    if not portfolio:
        return "❌ 포트폴리오가 없습니다. 먼저 `init_portfolio`로 생성해 주세요."

    # Convert amount to portfolio currency
    cur = currency.upper().strip()
    amount_in_pf = amount
    if cur != portfolio.currency:
        converted = await _convert_price(amount, cur, portfolio.currency)
        if converted is None:
            return f"❌ 환율 조회 실패: {cur} → {portfolio.currency}"
        amount_in_pf = converted

    # Get price in portfolio currency to calculate quantity
    quote = await _fetch_one(sym)
    if not quote:
        return f"❌ {sym} 시세를 조회할 수 없습니다."

    price_in_pf = quote.price
    if quote.currency != portfolio.currency:
        converted = await _convert_price(quote.price, quote.currency, portfolio.currency)
        if converted is None:
            return f"❌ 환율 조회 실패: {quote.currency} → {portfolio.currency}"
        price_in_pf = converted

    quantity = amount_in_pf / price_in_pf
    return await _execute_buy(sym, quantity)


@tool
async def sell(symbol: str, quantity: float = 0) -> str:
    """종목을 가상 매도합니다. 현재 시세로 즉시 체결됩니다.

    Args:
        symbol: 종목 심볼
        quantity: 매도 수량. 0이면 전량 매도.
    """
    portfolio = get_portfolio()
    if not portfolio:
        return "❌ 포트폴리오가 없습니다."

    if quantity < 0:
        return "❌ 수량은 0 이상이어야 합니다. 전량 매도는 0을 입력하세요."

    sym = symbol.upper().strip()
    position = get_position(sym)
    if not position:
        return f"❌ {sym} 보유 포지션이 없습니다."

    # 0 = sell all
    sell_qty = quantity if quantity > 0 else position.quantity

    # Float tolerance for "sell all by exact number"
    if sell_qty > position.quantity + 1e-9:
        return (
            f"❌ 보유 수량 초과\n"
            f"보유: {position.quantity:,.4g}\n"
            f"요청: {sell_qty:,.4g}"
        )
    sell_qty = min(sell_qty, position.quantity)  # clamp

    quote = await _fetch_one(sym)
    if not quote:
        return f"❌ {sym} 시세를 조회할 수 없습니다."

    # FX conversion: sell price in portfolio currency
    price_in_pf = quote.price
    if quote.currency != portfolio.currency:
        converted = await _convert_price(
            quote.price, quote.currency, portfolio.currency
        )
        if converted is None:
            return f"❌ 환율 조회 실패: {quote.currency} → {portfolio.currency}"
        price_in_pf = converted

    proceeds = price_in_pf * sell_qty
    realized = (price_in_pf - position.avg_cost) * sell_qty
    now = datetime.now(timezone.utc)

    # Update portfolio
    portfolio.cash_balance += proceeds
    portfolio.realized_pnl += realized
    upsert_portfolio(portfolio)

    # Update or delete position
    remaining = max(0.0, position.quantity - sell_qty)
    if remaining > 1e-9:
        position.quantity = remaining
        position.updated_at = now
        upsert_position(position)
    else:
        delete_position(sym)

    # Record order (in portfolio currency)
    create_order(Order(
        order_id=new_order_id(),
        symbol=sym,
        side="sell",
        quantity=sell_qty,
        price=price_in_pf,
        total_cost=proceeds,
        currency=portfolio.currency,
        created_at=now,
    ))

    pnl_emoji = "🔺" if realized >= 0 else "🔻"
    log.info("trade.sell", symbol=sym, qty=sell_qty, price=price_in_pf, pnl=realized)

    return (
        f"✅ **{sym}** {sell_qty:,.4g}개 매도 완료\n"
        f"체결가: {format_price(price_in_pf, portfolio.currency)}\n"
        f"총액: {format_price(proceeds, portfolio.currency)}\n"
        f"실현 손익: {pnl_emoji} {format_price(realized, portfolio.currency)}\n"
        f"잔고: {format_price(portfolio.cash_balance, portfolio.currency)}"
    )


# ---------------------------------------------------------------------------
# Orders / PnL
# ---------------------------------------------------------------------------

@tool
def get_order_history(limit: int = 10) -> str:
    """최근 주문 내역을 반환합니다.

    Args:
        limit: 반환할 주문 수 (기본 10, 최대 50)
    """
    orders = list_orders(limit=max(1, min(limit, 50)))
    if not orders:
        return "주문 내역이 없습니다."

    lines = ["## 📋 주문 내역\n"]
    for o in orders:
        emoji = "🟢 매수" if o.side == "buy" else "🔴 매도"
        ts = o.created_at.strftime("%m/%d %H:%M") if isinstance(o.created_at, datetime) else str(o.created_at)[:16]
        lines.append(
            f"- {ts} | {emoji} **{o.symbol}** {o.quantity:,.4g}개 "
            f"@ {format_price(o.price, o.currency)} "
            f"= {format_price(o.total_cost, o.currency)}"
        )
    return "\n".join(lines)


@tool
async def get_pnl_summary() -> str:
    """포트폴리오 전체 손익 요약을 반환합니다."""
    portfolio = get_portfolio()
    if not portfolio:
        return "포트폴리오가 없습니다."

    positions = list_positions()
    total_unrealized = 0.0
    failed_symbols: list[str] = []

    quotes = await _fetch_quotes([p.symbol for p in positions])
    for pos in positions:
        quote = quotes.get(pos.symbol)
        cur_price = await _quote_price_in_currency(
            quote, portfolio.currency
        ) if quote else None
        if cur_price is not None:
            total_unrealized += (cur_price - pos.avg_cost) * pos.quantity
        else:
            failed_symbols.append(pos.symbol)

    total_pnl = portfolio.realized_pnl + total_unrealized
    pnl_emoji = "🔺" if total_pnl >= 0 else "🔻"
    pnl_pct = (total_pnl / portfolio.initial_capital * 100) if portfolio.initial_capital else 0

    lines = [
        "## 💰 손익 요약",
        f"- 초기 자금: {format_price(portfolio.initial_capital, portfolio.currency)}",
        f"- 실현 PnL: {format_price(portfolio.realized_pnl, portfolio.currency)}",
        f"- 미실현 PnL: {format_price(total_unrealized, portfolio.currency)}",
        f"- **전체 PnL: {pnl_emoji} {format_price(total_pnl, portfolio.currency)} ({pnl_pct:+.2f}%)**",
    ]
    if failed_symbols:
        lines.append(f"\n⚠️ 시세 조회 실패: {', '.join(failed_symbols)} (해당 종목 제외)")
    return "\n".join(lines)


@tool
def get_pnl_chart(limit: int = 30) -> str:
    """포트폴리오 PnL 히스토리를 차트로 반환합니다.

    "수익률 차트 보여줘", "포트폴리오 추이" 같은 요청에 사용합니다.
    일별 PnL 스냅샷을 기반으로 꺾은선 그래프를 렌더링합니다.

    Args:
        limit: 조회할 스냅샷 수 (기본 30건, 최대 90건)
    """
    portfolio = get_portfolio()
    if not portfolio:
        return "포트폴리오가 없습니다."

    snapshots = list_pnl_snapshots(limit=min(max(limit, 1), 90))
    if not snapshots:
        return (
            "PnL 기록이 없습니다. 브리핑이 실행되면 자동으로 일별 스냅샷이 저장됩니다.\n"
            "내일 아침 브리핑 이후부터 차트를 볼 수 있습니다."
        )

    if len(snapshots) < 2:
        s = snapshots[0]
        return (
            f"아직 스냅샷이 1건({s.date})만 있습니다. "
            f"차트는 2일 이상의 데이터가 필요합니다.\n"
            f"총 자산: {format_price(s.total_value, portfolio.currency)}"
        )

    # Reverse to oldest → newest (list_pnl_snapshots returns newest first)
    snapshots = list(reversed(snapshots))

    # Single series: total asset value (PnL is derived from the shape)
    chart_data = {
        "type": "pnl",
        "tickers": ["총 자산"],
        "series": [{
            "symbol": "총 자산",
            "currency": portfolio.currency,
            "data": [
                {"time": s.date, "value": float(s.total_value)}
                for s in snapshots
            ],
        }],
    }

    first = snapshots[0]
    last = snapshots[-1]
    change = last.total_value - first.total_value
    change_pct = (change / first.total_value * 100) if first.total_value > 0 else 0
    emoji = "🔺" if change >= 0 else "🔻"

    lines = [
        f"## 📈 포트폴리오 추이 ({first.date} ~ {last.date})",
        f"- 시작: {format_price(first.total_value, portfolio.currency)}",
        f"- 현재: {format_price(last.total_value, portfolio.currency)}",
        f"- 변동: {emoji} {format_price(change, portfolio.currency)} ({change_pct:+.2f}%)",
        f"- 보유 종목: {last.positions_count}개",
        f"\n[CHART]\n{json.dumps(chart_data, ensure_ascii=False)}\n[/CHART]",
    ]
    return "\n".join(lines)
