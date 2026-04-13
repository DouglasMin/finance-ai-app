"""Analysis comparison tools — track changes across past analyses."""
import re

from langchain_core.tools import tool

from storage.ddb import query_by_sk_prefix

_TICKER_RE = re.compile(r"^[A-Za-z0-9/.\-]{1,20}$")
_MAX_DAYS = 30


def _safe_float(val: object) -> float | None:
    """Convert DynamoDB Decimal or other numeric to float, None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _fmt_price(snap: dict) -> str:
    price = _safe_float(snap.get("price"))
    if price is None:
        return "N/A"
    currency = snap.get("currency", "$")
    return f"{currency} {price:,.2f}"


@tool
def compare_analysis(ticker: str, days: int = 7) -> str:
    """특정 종목의 과거 분석 기록을 조회하고 변화를 추적합니다.

    Args:
        ticker: 종목 심볼 (예: BTC, AAPL, 005930)
        days: 조회할 최근 일수 (기본 7일, 최대 30일)
    """
    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        return f"잘못된 종목 형식입니다: {ticker}"
    days = min(max(days, 1), _MAX_DAYS)

    snapshots = query_by_sk_prefix(
        f"SNAP#{ticker}#", limit=days, ascending=False
    )
    if not snapshots:
        return (
            f"{ticker}의 이전 분석 기록이 없습니다. "
            "먼저 해당 종목을 분석해 주세요."
        )

    parts: list[str] = [
        f"## {ticker} 분석 변화 추적 (최근 {len(snapshots)}건)\n"
    ]

    for i, snap in enumerate(snapshots):
        date = snap.get("date", "?")
        change = _safe_float(snap.get("change_pct"))
        sentiment = snap.get("sentiment", "")
        outlook = snap.get("outlook", "")

        change_str = f" ({change:+.2f}%)" if change is not None else ""

        parts.append(f"### {date}")
        parts.append(f"- 가격: {_fmt_price(snap)}{change_str}")
        if sentiment:
            parts.append(f"- 심리: {sentiment}")
        if outlook:
            parts.append(f"- 전망: {outlook}")

        risks = snap.get("risk_factors", [])
        if risks:
            parts.append(f"- 리스크: {', '.join(str(r) for r in risks)}")

        # Delta vs previous snapshot
        if i < len(snapshots) - 1:
            prev = snapshots[i + 1]
            price = _safe_float(snap.get("price"))
            prev_price = _safe_float(prev.get("price"))
            if price is not None and prev_price is not None and prev_price != 0:
                delta = ((price - prev_price) / prev_price) * 100
                direction = (
                    "상승" if delta > 0 else "하락" if delta < 0 else "보합"
                )
                parts.append(f"- 전일 대비: {delta:+.2f}% ({direction})")
            prev_sentiment = prev.get("sentiment", "")
            if (
                sentiment
                and prev_sentiment
                and sentiment != prev_sentiment
            ):
                parts.append(
                    f"- 심리 변화: {prev_sentiment} → {sentiment}"
                )

        parts.append("")

    return "\n".join(parts)


@tool
def watchlist_changes(days: int = 3) -> str:
    """워치리스트 전체 종목의 최근 분석 변화를 한눈에 보여줍니다.

    Args:
        days: 조회할 최근 일수 (기본 3일, 최대 30일)
    """
    days = min(max(days, 1), _MAX_DAYS)

    watch_items = query_by_sk_prefix("WATCH#")
    if not watch_items:
        return "워치리스트가 비어 있습니다."

    tickers = [item["symbol"] for item in watch_items if "symbol" in item]
    if not tickers:
        return "워치리스트에 유효한 종목이 없습니다."

    parts: list[str] = [f"## 워치리스트 변화 추적 (최근 {days}일)\n"]
    has_data = False

    for ticker in tickers:
        snapshots = query_by_sk_prefix(
            f"SNAP#{ticker}#", limit=days, ascending=False
        )
        if not snapshots:
            parts.append(f"**{ticker}** — 분석 기록 없음\n")
            continue

        has_data = True
        latest = snapshots[0]
        date = latest.get("date", "?")
        sentiment = latest.get("sentiment", "")

        header = f"**{ticker}** ({date}) — {_fmt_price(latest)}"
        change = _safe_float(latest.get("change_pct"))
        if change is not None:
            header += f" ({change:+.2f}%)"
        parts.append(header)

        if sentiment:
            parts.append(f"  심리: {sentiment}")

        # Period change vs oldest snapshot in range
        if len(snapshots) > 1:
            oldest = snapshots[-1]
            cur_price = _safe_float(latest.get("price"))
            old_price = _safe_float(oldest.get("price"))
            if (
                cur_price is not None
                and old_price is not None
                and old_price != 0
            ):
                period_delta = ((cur_price - old_price) / old_price) * 100
                parts.append(f"  {days}일간 변동: {period_delta:+.2f}%")
            old_sentiment = oldest.get("sentiment", "")
            if (
                sentiment
                and old_sentiment
                and sentiment != old_sentiment
            ):
                parts.append(
                    f"  심리 변화: {old_sentiment} → {sentiment}"
                )

        parts.append("")

    if not has_data:
        parts.append("아직 분석 기록이 없습니다. 먼저 종목을 분석해 주세요.")

    return "\n".join(parts)
