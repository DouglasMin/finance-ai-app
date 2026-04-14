"""Multi-ticker comparison tool — fetches market data for multiple tickers
and returns a markdown comparison table + chart data for frontend rendering.

Chart data is embedded in a [CHART]...[/CHART] block so the frontend can
extract and render it with lightweight-charts while displaying the markdown
table in the chat bubble.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from infra.logging_config import get_logger
from nodes.fetch_market import _categorize, _fetch_one
from schemas.market import MarketQuote
from tools.sources import okx, pykrx_adapter, frankfurter

log = get_logger("compare_tickers")

_SPARKLINE_DAYS = 7


async def _fetch_history(ticker: str) -> list[float]:
    """Fetch sparkline history for a ticker. Returns empty list on failure."""
    category = await _categorize(ticker)
    try:
        if category == "crypto":
            return await okx.get_crypto_history(ticker, days=_SPARKLINE_DAYS)
        if category == "kr_stock":
            return await pykrx_adapter.get_kr_history(ticker, days=_SPARKLINE_DAYS)
        if category == "fx":
            parts = ticker.split("/") if "/" in ticker else ["USD", "KRW"]
            return await frankfurter.get_fx_history(
                parts[0], parts[1], days=_SPARKLINE_DAYS
            )
        log.warning(
            "compare.history.unsupported_category",
            ticker=ticker,
            category=category,
        )
    except Exception as e:
        log.warning("compare.history.failed", ticker=ticker, error=str(e))
    return []


def _format_price(price: float, currency: str) -> str:
    if currency == "KRW":
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"


def _build_chart_data(
    tickers: list[str],
    histories: dict[str, list[float]],
    currencies: dict[str, str],
) -> dict:
    """Build chart data payload for lightweight-charts on the frontend."""
    today = datetime.now(timezone.utc).date()
    series = []
    for ticker in tickers:
        history = histories.get(ticker, [])
        if not history:
            continue
        data_points = []
        for i, value in enumerate(history):
            day = today - timedelta(days=len(history) - 1 - i)
            data_points.append({"time": day.isoformat(), "value": value})
        series.append({
            "symbol": ticker,
            "currency": currencies.get(ticker, "USD"),
            "data": data_points,
        })
    return {"type": "comparison", "tickers": tickers, "series": series}


@tool
async def compare_tickers(
    tickers: list[str],
    lang: str = "ko",
) -> str:
    """종목 시세 차트 및 비교 도구. 1~5개 종목의 시세를 테이블과 차트 데이터로 반환합니다.

    단일 종목 차트: "삼성전자 차트 보여줘", "BTC 차트"
    멀티 비교: "BTC랑 ETH 비교해줘", "삼성전자 SK하이닉스 비교"

    Args:
        tickers: 종목 리스트 (1~5개). 크립토는 BTC/ETH,
                 미국 주식은 AAPL/NVDA, 한국 주식은 6자리 코드.
        lang: 응답 언어 ("ko" 또는 "en", 기본 ko)

    Returns:
        시세 테이블 (마크다운) + 차트 데이터 ([CHART] 블록)
    """
    if not tickers:
        return "종목을 1개 이상 입력해주세요."
    tickers = tickers[:5]

    # Parallel fetch: quotes + history for all tickers
    quote_coros = [_fetch_one(t) for t in tickers]
    history_coros = [_fetch_history(t) for t in tickers]
    all_results = await asyncio.gather(
        *quote_coros, *history_coros, return_exceptions=True
    )

    n = len(tickers)
    quotes = all_results[:n]
    histories_raw = all_results[n:]

    quote_map: dict[str, MarketQuote] = {}
    history_map: dict[str, list[float]] = {}
    currency_map: dict[str, str] = {}

    for ticker, q in zip(tickers, quotes):
        if isinstance(q, MarketQuote):
            quote_map[ticker] = q
            currency_map[ticker] = q.currency
        elif isinstance(q, Exception):
            log.warning("compare.quote.failed", ticker=ticker, error=str(q))

    for ticker, h in zip(tickers, histories_raw):
        if isinstance(h, list):
            history_map[ticker] = h
        elif isinstance(h, Exception):
            log.warning("compare.history.gather_failed", ticker=ticker, error=str(h))

    if not quote_map:
        return "시세 데이터를 가져오지 못했습니다."

    # Build markdown comparison table
    header = "| 항목 | " + " | ".join(f"**{t}**" for t in tickers) + " |"
    separator = "|------|" + "|".join("------" for _ in tickers) + "|"

    rows: list[str] = []

    # Price row
    price_cells = []
    for t in tickers:
        q = quote_map.get(t)
        price_cells.append(_format_price(q.price, q.currency) if q else "--")
    rows.append("| 현재가 | " + " | ".join(price_cells) + " |")

    # Change % row
    change_cells = []
    for t in tickers:
        q = quote_map.get(t)
        if q and q.change_pct is not None:
            emoji = "🔺" if q.change_pct >= 0 else "🔻"
            change_cells.append(f"{emoji} {q.change_pct:+.2f}%")
        else:
            change_cells.append("--")
    rows.append("| 변동률 | " + " | ".join(change_cells) + " |")

    # High row
    high_cells = []
    for t in tickers:
        q = quote_map.get(t)
        high_cells.append(
            _format_price(q.high, q.currency) if q and q.high is not None else "--"
        )
    rows.append("| 고가 | " + " | ".join(high_cells) + " |")

    # Low row
    low_cells = []
    for t in tickers:
        q = quote_map.get(t)
        low_cells.append(
            _format_price(q.low, q.currency) if q and q.low is not None else "--"
        )
    rows.append("| 저가 | " + " | ".join(low_cells) + " |")

    # Volume row
    vol_cells = []
    for t in tickers:
        q = quote_map.get(t)
        if q and q.volume is not None:
            if q.volume >= 1_000_000:
                vol_cells.append(f"{q.volume / 1_000_000:.1f}M")
            elif q.volume >= 1_000:
                vol_cells.append(f"{q.volume / 1_000:.1f}K")
            else:
                vol_cells.append(f"{q.volume:.0f}")
        else:
            vol_cells.append("--")
    rows.append("| 거래량 | " + " | ".join(vol_cells) + " |")

    # 7-day change row (from sparkline)
    week_cells = []
    for t in tickers:
        h = history_map.get(t, [])
        if len(h) >= 2 and h[0] != 0:
            pct = ((h[-1] / h[0]) - 1) * 100
            emoji = "🔺" if pct >= 0 else "🔻"
            week_cells.append(f"{emoji} {pct:+.2f}%")
        else:
            week_cells.append("--")
    rows.append("| 7일 변동 | " + " | ".join(week_cells) + " |")

    table = "\n".join([header, separator] + rows)

    # Build chart data
    chart_data = _build_chart_data(tickers, history_map, currency_map)
    chart_block = f"\n\n[CHART]\n{json.dumps(chart_data, ensure_ascii=False)}\n[/CHART]"

    log.info(
        "compare.success",
        tickers=tickers,
        quotes=len(quote_map),
        histories=len(history_map),
    )

    return f"## 📊 종목 비교\n\n{table}{chart_block}"
