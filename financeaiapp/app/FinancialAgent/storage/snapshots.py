"""Analysis snapshot storage — saves per-ticker snapshots to DDB.

Each analysis run saves a snapshot per ticker with market data and
structured analysis fields. SK pattern: SNAP#{TICKER}#{YYYY-MM-DD}.
Same-day re-analysis overwrites the previous snapshot (latest wins).
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from infra.logging_config import get_logger
from schemas.analysis import AnalysisResult
from schemas.market import MarketSnapshot
from storage.ddb import put_item

log = get_logger("snapshots")

_TICKER_RE = re.compile(r"^[A-Za-z0-9/.\-]{1,20}$")


def _validate_ticker(ticker: str) -> str | None:
    """Return uppercased ticker if valid, None otherwise."""
    t = ticker.strip().upper()
    if _TICKER_RE.match(t):
        return t
    return None


def save_snapshots(
    tickers: list[str],
    market: MarketSnapshot,
    result: Optional[AnalysisResult] = None,
) -> None:
    """Save per-ticker analysis snapshots to DDB.

    Called after each analysis. Failures are logged per-ticker but never
    propagated so the main analysis flow is unaffected.
    """
    if not tickers:
        return

    kst = datetime.now(timezone.utc) + timedelta(hours=9)
    date_str = kst.strftime("%Y-%m-%d")

    prices: dict[str, dict] = {}
    for q in market.quotes:
        prices[q.symbol] = {
            "price": float(q.price),
            "change_pct": (
                float(q.change_pct) if q.change_pct is not None else None
            ),
            "currency": q.currency,
        }

    saved = 0
    for ticker in tickers:
        clean = _validate_ticker(ticker)
        if not clean:
            log.warning("snapshots.invalid_ticker", ticker=ticker)
            continue
        try:
            sk = f"SNAP#{clean}#{date_str}"
            attrs: dict = {"ticker": clean, "date": date_str}

            if clean in prices:
                attrs.update(prices[clean])
            elif ticker in prices:
                attrs.update(prices[ticker])

            if result:
                attrs["sentiment"] = result.sentiment_overview
                attrs["outlook"] = result.outlook
                attrs["risk_factors"] = result.risk_factors
                attrs["risk_count"] = len(result.risk_factors)

            put_item(sk, attrs)
            saved += 1
        except Exception as e:
            log.warning(
                "snapshots.save_failed", ticker=clean, error=str(e)
            )

    if saved:
        log.info("snapshots.saved", count=saved, date=date_str)
