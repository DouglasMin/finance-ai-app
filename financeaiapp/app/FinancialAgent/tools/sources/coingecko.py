"""CoinGecko adapter — crypto symbol → full name lookup (free, no key).

Uses `/api/v3/coins/markets` sorted by market cap so popular symbols
(BTC, ETH, PEPE) resolve to their canonical coin, not obscure low-cap
tokens that happen to share a ticker.
"""
import asyncio

import httpx

from infra.logging_config import get_logger

log = get_logger("coingecko")
_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
_TOP_COUNT = 250  # top 250 by market cap covers virtually all user queries

_symbol_to_name: dict[str, str] | None = None
_load_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _load_lock
    if _load_lock is None:
        _load_lock = asyncio.Lock()
    return _load_lock


async def _load_list() -> dict[str, str]:
    """Fetch top coins by market cap and build symbol → name map.

    Top-1000 coins cover practically all user queries. Market-cap order
    means BTC → Bitcoin (not the low-cap coin that also uses BTC symbol).
    Concurrent callers share one HTTP burst via the lock. On failure,
    does NOT poison the cache — next call retries.
    """
    global _symbol_to_name
    if _symbol_to_name is not None:
        return _symbol_to_name

    async with _get_lock():
        if _symbol_to_name is not None:
            return _symbol_to_name
        mapping: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    _MARKETS_URL,
                    params={
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": _TOP_COUNT,
                        "page": 1,
                    },
                )
                r.raise_for_status()
                for coin in r.json():
                    sym = (coin.get("symbol") or "").upper()
                    name = coin.get("name") or ""
                    if sym and name and sym not in mapping:
                        mapping[sym] = name
            _symbol_to_name = mapping
            log.info("coingecko.list.loaded", count=len(mapping))
            return _symbol_to_name
        except Exception as e:
            log.warning("coingecko.list.failed", error=str(e))
            return {}  # transient — do not cache the failure


async def get_coin_name(symbol: str) -> str | None:
    """Return CoinGecko full name for symbol, or None if unknown."""
    mapping = await _load_list()
    return mapping.get(symbol.upper())
