"""Shared formatting utilities — price, volume, percentage display.

Adaptive precision for prices: KRW uses whole numbers, while USD-denominated
assets auto-scale decimal places so sub-penny crypto (PEPE, SHIB) shows
meaningful digits instead of $0.00.
"""


def format_price(price: float, currency: str = "USD") -> str:
    """Format a price with adaptive decimal places.

    KRW       → ₩1,234,567        (no decimals)
    >= 1      → $1,234.56         (2 decimals)
    >= 0.01   → $0.1234           (4 decimals)
    >= 0.0001 → $0.001234         (6 decimals)
    < 0.0001  → $0.00000123       (8 decimals, covers SHIB/PEPE)
    """
    if currency == "KRW":
        return f"₩{price:,.0f}"
    prefix = "$" if currency == "USD" else f"{currency} "
    abs_price = abs(price)
    if abs_price >= 1:
        return f"{prefix}{price:,.2f}"
    if abs_price >= 0.01:
        return f"{prefix}{price:,.4f}"
    if abs_price >= 0.0001:
        return f"{prefix}{price:,.6f}"
    return f"{prefix}{price:,.8f}"


def format_volume(volume: float) -> str:
    """Compact volume formatting: 1.2M, 45.3K, etc."""
    if volume >= 1_000_000_000:
        return f"{volume / 1_000_000_000:.1f}B"
    if volume >= 1_000_000:
        return f"{volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"{volume / 1_000:.1f}K"
    return f"{volume:.0f}"
