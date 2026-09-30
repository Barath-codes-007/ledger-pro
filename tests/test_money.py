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


def test_dashboard_totals_are_exact_with_many_small_amounts(alice):
    """20 additions of 0.10 must equal exactly 2.00 - the classic float trap."""
    from conftest import post
    for _ in range(20):
        post(alice, "/expenses/add", {"category": "Food", "amount": "0.10", "date": "2026-09-10",
                                       "payment_mode": "Cash", "description": "x"},
             content_type="multipart/form-data")
    html = alice.get("/dashboard").get_data(as_text=True)
    assert "2.00" in html
    assert "1.9999999999" not in html and "2.0000000000" not in html
