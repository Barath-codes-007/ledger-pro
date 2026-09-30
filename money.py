"""
money.py
Deterministic money handling for Ledger. All arithmetic happens in integer
minor units (paise for INR, cents for USD, etc.) via Decimal conversion, so
floating-point rounding errors never reach a balance or a report.
"""

from decimal import Decimal, ROUND_HALF_UP

MINOR_UNITS = 100  # every supported currency here uses 2 decimal places


def to_minor(amount) -> int:
    """Convert a user-facing amount (str, float, int, Decimal) to integer minor units."""
    d = Decimal(str(amount))
    return int((d * MINOR_UNITS).quantize(0, rounding=ROUND_HALF_UP))


def to_major(minor: int) -> Decimal:
    """Convert integer minor units back to a Decimal major amount, e.g. 3030 -> 30.30."""
    return (Decimal(minor) / MINOR_UNITS).quantize(Decimal("0.01"))


def format_amount(minor: int, symbol: str) -> str:
    major = to_major(minor)
    sign = "-" if major < 0 else ""
    return f"{sign}{symbol}{abs(major):,.2f}"
