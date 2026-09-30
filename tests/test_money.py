from decimal import Decimal
from money import to_minor, to_major


def test_to_minor_basic():
    assert to_minor("10.10") == 1010
    assert to_minor("20.20") == 2020


def test_no_float_rounding_error_on_addition():
    total = to_minor("10.10") + to_minor("20.20")
    assert to_major(total) == Decimal("30.30")


def test_to_minor_rounds_half_up():
    assert to_minor("1.005") == 101
