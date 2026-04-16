"""Paper trading tools — virtual portfolio management for the orchestrator.

All trades execute at current market price (from OKX/AV/pykrx/Frankfurter).
No real money, no exchange API — prices are fetched the same way as the
research tool, then recorded in DynamoDB.

Concurrency note: single-user system with serial agent execution. DDB writes
are not atomic (no conditional expressions) but race conditions are not
practical in this deployment model.
"""
import asyncio
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
        if quote:
            market_val = quote.price * pos.quantity
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
        cur_price = quote.price if quote else 0
        pnl = (cur_price - pos.avg_cost) * pos.quantity
        pnl_pct = ((cur_price / pos.avg_cost - 1) * 100) if pos.avg_cost else 0
        emoji = "🔺" if pnl >= 0 else "🔻"
        price_str = format_price(cur_price, pos.currency) if quote else "N/A"

        lines.append(
            f"| {pos.symbol} | {pos.quantity:,.4g} "
            f"| {format_price(pos.avg_cost, pos.currency)} "
            f"| {price_str} "
            f"| {emoji} {pnl_pct:+.2f}% |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Buy / Sell
# ---------------------------------------------------------------------------

@tool
async def buy(symbol: str, quantity: float = 0, amount: float = 0) -> str:
    """종목을 가상 매수합니다. 현재 시세로 즉시 체결됩니다.

    quantity 또는 amount 중 하나를 지정합니다.
    - quantity: 매수 수량 (예: 0.1 = 0.1개)
    - amount: 포트폴리오 통화 기준 매수 금액 (예: 5000000 = 500만원어치).
      수량은 현재가로 자동 계산됩니다.

    통화가 다른 종목도 자동 환율 변환합니다 (예: KRW 포트폴리오 → USD 코인).

    Args:
        symbol: 종목 심볼 (BTC, AAPL, 005930 등)
        quantity: 매수 수량 (amount와 동시 사용 불가)
        amount: 포트폴리오 통화 기준 매수 금액
    """
    portfolio = get_portfolio()
    if not portfolio:
        return "❌ 포트폴리오가 없습니다. 먼저 `init_portfolio`로 생성해 주세요."

    if quantity <= 0 and amount <= 0:
        return "❌ quantity 또는 amount 중 하나를 지정해 주세요."

    sym = symbol.upper().strip()

    # Classify + fetch price BEFORE touching balances
    category = await classify_ticker(sym)
    quote = await _fetch_one(sym)
    if not quote:
        return f"❌ {sym} 시세를 조회할 수 없습니다."

    # FX conversion: convert quote price to portfolio currency
    price_in_pf_currency = quote.price
    fx_info = ""
    if quote.currency != portfolio.currency:
        converted = await _convert_price(
            quote.price, quote.currency, portfolio.currency
        )
        if converted is None:
            return (
                f"❌ 환율 조회 실패: {quote.currency} → {portfolio.currency}\n"
                f"잠시 후 다시 시도해 주세요."
            )
        price_in_pf_currency = converted
        rate = price_in_pf_currency / quote.price
        fx_info = f"\n환율: 1 {quote.currency} = {format_price(rate, portfolio.currency)}"

    # Calculate quantity from amount if specified
    if amount > 0:
        quantity = amount / price_in_pf_currency

    total_cost = price_in_pf_currency * quantity
    if total_cost > portfolio.cash_balance:
        return (
            f"❌ 잔고 부족\n"
            f"필요: {format_price(total_cost, portfolio.currency)}\n"
            f"잔고: {format_price(portfolio.cash_balance, portfolio.currency)}"
        )

    now = datetime.now(timezone.utc)

    # Update portfolio cash
    portfolio.cash_balance -= total_cost
    upsert_portfolio(portfolio)

    # Update or create position (avg cost in portfolio currency)
    existing = get_position(sym)
    if existing:
        new_qty = existing.quantity + quantity
        new_avg = (
            (existing.avg_cost * existing.quantity + price_in_pf_currency * quantity)
            / new_qty
        )
        existing.quantity = new_qty
        existing.avg_cost = new_avg
        existing.updated_at = now
        upsert_position(existing)
    else:
        upsert_position(Position(
            symbol=sym,
            category=category,
            quantity=quantity,
            avg_cost=price_in_pf_currency,
            currency=portfolio.currency,
            opened_at=now,
            updated_at=now,
        ))

    # Record order
    create_order(Order(
        order_id=new_order_id(),
        symbol=sym,
        side="buy",
        quantity=quantity,
        price=price_in_pf_currency,
        total_cost=total_cost,
        currency=portfolio.currency,
        created_at=now,
    ))

    log.info("trade.buy", symbol=sym, qty=quantity, price=price_in_pf_currency)

    return (
        f"✅ **{sym}** {quantity:,.6g}개 매수 완료\n"
        f"체결가: {format_price(price_in_pf_currency, portfolio.currency)}"
        f" (원가: {format_price(quote.price, quote.currency)}){fx_info}\n"
        f"총액: {format_price(total_cost, portfolio.currency)}\n"
        f"잔고: {format_price(portfolio.cash_balance, portfolio.currency)}"
    )


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
        if quote:
            total_unrealized += (quote.price - pos.avg_cost) * pos.quantity
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
