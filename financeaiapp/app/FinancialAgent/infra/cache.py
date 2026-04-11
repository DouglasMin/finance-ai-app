"""TTL caches for market and news data."""
from cachetools import TTLCache

# 30 seconds for prices, 5 min for news
_market_cache: TTLCache = TTLCache(maxsize=200, ttl=30)
_news_cache: TTLCache = TTLCache(maxsize=200, ttl=300)


def market_cache() -> TTLCache:
    return _market_cache


def news_cache() -> TTLCache:
    return _news_cache


def cache_key(*parts) -> str:
    return "|".join(str(p) for p in parts)
