"""
copilot.py
Finance Copilot (#52-53): a rule-based assistant, NOT a language model.
Every answer is built from a deterministic calculation already used
elsewhere in the app (services.py / direct queries) and the numbers are
interpolated into a template string - the matching logic never invents a
figure. If no question pattern matches, it says so plainly rather than
guessing. Labels every number as what it is (actual, calculated, or
estimated) per #53.
"""

import re
from datetime import datetime

import services
from money import to_major


def _month_bounds(today=None):
    today = today or datetime.now()
    start = today.replace(day=1).strftime("%Y-%m-%d")
    return start, today.strftime("%Y-%m-%d"), today


def _last_month_bounds(today=None):
    today = today or datetime.now()
    first_of_this = today.replace(day=1)
    last_month_end = first_of_this.replace(day=1)
    # Step back one day from the 1st to land in the previous month.
    from datetime import timedelta
    last_month_end = first_of_this - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    return last_month_start.strftime("%Y-%m-%d"), last_month_end.strftime("%Y-%m-%d")


def answer(conn, user_id, question, currency_symbol="₹"):
    q = question.lower().strip()

    def fmt(minor):
        return f"{currency_symbol}{to_major(minor):,.2f}"

    # How much did I spend this month?
    if re.search(r"how much.*spen.*(this month|month)", q) or q in ("spending this month", "monthly spend"):
        start, end, today = _month_bounds()
        spent = conn.execute(
            "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
            (user_id, start, end)).fetchone()["t"] or 0
        return f"You've spent {fmt(spent)} so far this month (actual, from your recorded expenses)."

    # How much did I save?
    if re.search(r"how much.*sav", q):
        start, end, _ = _month_bounds()
        income = conn.execute(
            "SELECT COALESCE(SUM(amount_minor),0) t FROM income WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
            (user_id, start, end)).fetchone()["t"] or 0
        expense = conn.execute(
            "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
            (user_id, start, end)).fetchone()["t"] or 0
        saved = income - expense
        return f"This month you've saved {fmt(saved)} (actual: {fmt(income)} income minus {fmt(expense)} expenses)."

    # Where did most of my money go? / biggest expenses / spending by category
    if re.search(r"(where did most|biggest expense|spending by category|where.*money go)", q):
        rows = conn.execute(
            "SELECT category, SUM(amount_minor) t FROM expenses WHERE user_id=? AND is_deleted=0 "
            "GROUP BY category ORDER BY t DESC LIMIT 5", (user_id,)).fetchall()
        if not rows:
            return "You don't have any recorded expenses yet, so there's nothing to break down."
        lines = [f"{r['category']}: {fmt(r['t'])}" for r in rows]
        return "Your top spending categories (actual, all-time) are: " + "; ".join(lines) + "."

    # Compare this month with last month
    if re.search(r"compare.*(month|last month)", q):
        this_start, this_end, _ = _month_bounds()
        last_start, last_end = _last_month_bounds()
        this_amt = conn.execute(
            "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
            (user_id, this_start, this_end)).fetchone()["t"] or 0
        last_amt = conn.execute(
            "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
            (user_id, last_start, last_end)).fetchone()["t"] or 0
        if last_amt == 0:
            return f"This month's spending is {fmt(this_amt)} (actual). You had no recorded spending last month to compare against."
        change = round((this_amt - last_amt) / last_amt * 100, 1)
        direction = "more" if change > 0 else "less"
        return (f"This month: {fmt(this_amt)} vs last month: {fmt(last_amt)} (both actual) — "
                f"that's {abs(change)}% {direction}.")

    # What subscriptions do I have?
    if re.search(r"subscription", q):
        rows = conn.execute(
            "SELECT category, amount, frequency, next_date, description FROM recurring_expenses "
            "WHERE user_id=? AND active=1 ORDER BY next_date", (user_id,)).fetchall()
        if not rows:
            return "You don't have any active recurring expenses tracked yet."
        lines = [f"{(r['description'] or r['category'])} ({currency_symbol}{r['amount']:.2f}/{r['frequency'].lower()})"
                 for r in rows]
        return "Your tracked recurring payments (actual, as entered) are: " + "; ".join(lines) + "."

    # Net worth
    if re.search(r"net worth", q):
        nw = services.net_worth(conn, user_id)
        return (f"Your current net worth is {fmt(nw['net_worth_minor'])} "
                f"(actual: {fmt(nw['assets_minor'])} assets minus {fmt(nw['liabilities_minor'])} liabilities).")

    # 30-day forecast
    if re.search(r"(forecast|next 30 days|projected balance)", q):
        f_data = services.forecast_30_day_balance(conn, user_id)
        return (f"Estimated balance in 30 days: {fmt(f_data['projected_balance_minor'])} "
                f"(ESTIMATE, based on your recent spending rate and known upcoming bills — not a guarantee).")

    return ("I can answer questions like \"How much did I spend this month?\", \"Where did most of my "
            "money go?\", \"Compare this month with last month\", \"What subscriptions do I have?\", "
            "\"How much did I save?\", \"What's my net worth?\" or \"What's my 30-day forecast?\" — "
            "try rephrasing along those lines.")
