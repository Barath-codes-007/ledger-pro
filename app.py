"""
app.py
Main Flask application for the Expense Tracker.
Handles authentication, expenses, income, budget, reports, settings and APIs
that power the dashboard charts and live search.
"""

import os
import io
import csv
import logging
import secrets
import calendar
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_file, abort, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd

from database import get_db_connection, init_db, now_iso, backfill_minor_units
import security
import services
import repositories
from money import to_minor, to_major, format_amount

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ledger")

IS_PRODUCTION = bool(os.environ.get("RENDER")) or os.environ.get("LEDGER_ENV", "").lower() == "production"
DEBUG = os.environ.get("LEDGER_DEBUG", "").lower() in ("1", "true") and not IS_PRODUCTION

_secret = os.environ.get("SECRET_KEY")
if not _secret:
    # No hard-coded key. Without SECRET_KEY, sessions reset on every restart.
    _secret = secrets.token_hex(32)
    log.warning("SECRET_KEY is not set; using a temporary key. Set SECRET_KEY in your environment.")
app.secret_key = _secret

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Receipts live outside /static so they are never served publicly.
app.config["RECEIPT_DIR"] = os.environ.get("LEDGER_RECEIPT_DIR", os.path.join(BASE_DIR, "instance", "receipts"))
app.config["LEGACY_UPLOAD_DIR"] = os.path.join(BASE_DIR, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB max upload
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)
login_limiter = security.LoginRateLimiter()
api_limiter = security.ApiRateLimiter()
DEFAULT_CURRENCY = "INR"

CATEGORY_ICONS = {
    "Food": "fa-utensils",
    "Groceries": "fa-basket-shopping",
    "Transport": "fa-car",
    "Shopping": "fa-bag-shopping",
    "Entertainment": "fa-film",
    "Bills": "fa-file-invoice-dollar",
    "Health": "fa-briefcase-medical",
    "Education": "fa-graduation-cap",
    "Rent": "fa-house",
    "Travel": "fa-plane",
    "Subscriptions": "fa-rotate",
    "Insurance": "fa-shield-halved",
    "Gifts": "fa-gift",
    "Other": "fa-receipt",
}
PAYMENT_MODES = ["Cash", "Credit Card", "Debit Card", "UPI", "Net Banking", "Wallet"]
CURRENCIES = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥", "AUD": "A$", "CAD": "C$"}
LANGUAGES = ["English", "Spanish", "French", "German", "Hindi"]


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")


@app.before_request
def protect_request():
    """CSRF check for state-changing requests; hide legacy public uploads."""
    if request.path.startswith("/static/uploads/") and request.path != "/static/uploads/.gitkeep":
        abort(404)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not security.csrf_valid(session, submitted):
            log.warning("csrf_rejected path=%s ip=%s", request.path, client_ip())
            abort(400, description="Your session expired. Please go back, refresh and try again.")


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


def get_current_user():
    if "user_id" not in session:
        return None
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()
    return user


def get_user_currency_symbol(user):
    if not user:
        return CURRENCIES[DEFAULT_CURRENCY]
    return CURRENCIES.get(user["currency"], CURRENCIES[DEFAULT_CURRENCY])


@app.context_processor
def inject_globals():
    """Make user info and helpers available to every template."""
    user = get_current_user()
    return dict(
        current_user=user,
        currency_symbol=get_user_currency_symbol(user),
        user_currency=(user["currency"] if user else DEFAULT_CURRENCY),
        csrf_token=lambda: security.get_csrf_token(session),
        category_icons=CATEGORY_ICONS,
        payment_modes=PAYMENT_MODES,
        currencies=CURRENCIES,
        languages=LANGUAGES,
        now_year=datetime.now().year,
    )


# ---------------------------------------------------------------------------
# Static landing / auth routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for("signup"))
        pw_error = security.validate_password(password)
        if pw_error:
            flash(pw_error, "error")
            return redirect(url_for("signup"))
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("signup"))

        conn = get_db_connection()
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.close()
            flash("An account with that email already exists.", "error")
            return redirect(url_for("signup"))

        password_hash = generate_password_hash(password)
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, email, password_hash, now_iso())
        )
        user_id = cur.lastrowid
        conn.execute(
            "INSERT INTO settings (user_id, currency, language, dark_mode) VALUES (?, ?, 'English', 0)",
            (user_id, DEFAULT_CURRENCY)
        )
        conn.execute("UPDATE users SET currency = ? WHERE id = ?", (DEFAULT_CURRENCY, user_id))
        conn.commit()
        conn.close()

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = (client_ip(), email)

        if login_limiter.is_blocked(key):
            log.warning("login_rate_limited ip=%s", key[0])
            flash("Too many failed attempts. Please try again in 15 minutes.", "error")
            return render_template("login.html"), 429

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            login_limiter.reset(key)
            session.clear()  # rotate session on privilege change
            session.permanent = True
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            services.record_audit(conn, user["id"], "login_success", "user", user["id"], {"ip": client_ip()})
            conn.commit()
            conn.close()
            log.info("login_success user_id=%s", user["id"])
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("dashboard"))

        conn.close()
        login_limiter.record_failure(key)
        log.warning("login_failed ip=%s", key[0])
        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    conn = get_db_connection()

    today = datetime.now()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    next_month_start = (today.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m-%d")

    total_income_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS t FROM income WHERE user_id = ?", (uid,)
    ).fetchone()["t"]
    total_expense_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS t FROM expenses WHERE user_id = ?", (uid,)
    ).fetchone()["t"]
    total_income = float(to_major(total_income_minor))
    total_expense = float(to_major(total_expense_minor))
    balance = total_income - total_expense

    month_expense_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS t FROM expenses WHERE user_id = ? AND date >= ? AND date < ?",
        (uid, month_start, next_month_start)
    ).fetchone()["t"]
    month_income_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS t FROM income WHERE user_id = ? AND date >= ? AND date < ?",
        (uid, month_start, next_month_start)
    ).fetchone()["t"]
    month_expense = float(to_major(month_expense_minor))
    month_income = float(to_major(month_income_minor))


    txns_today = conn.execute(
        "SELECT COUNT(*) AS c FROM expenses WHERE user_id = ? AND date = ?", (uid, today_str)
    ).fetchone()["c"]
    txns_month = conn.execute(
        "SELECT COUNT(*) AS c FROM expenses WHERE user_id = ? AND date >= ? AND date < ?", (uid, month_start, next_month_start)
    ).fetchone()["c"]

    days_elapsed = today.day
    avg_daily = round(month_expense / days_elapsed, 2) if days_elapsed else 0

    budget_row = conn.execute(
        "SELECT * FROM budget WHERE user_id = ? AND month = ? AND year = ?",
        (uid, today.month, today.year)
    ).fetchone()
    monthly_budget = budget_row["amount"] if budget_row else 0
    savings_goal = budget_row["savings_goal"] if budget_row else 0
    budget_pct = round((month_expense / monthly_budget) * 100, 1) if monthly_budget else 0
    remaining_budget = monthly_budget - month_expense

    recent = conn.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 6", (uid,)
    ).fetchall()

    # Transparent metrics instead of an opaque "health score" (see #54): each
    # number here is directly traceable to a stored value, nothing blended.
    savings_rate = round(((total_income - total_expense) / total_income * 100), 1) if total_income else 0

    services.process_due_recurring(conn, uid, today_str)
    nw = services.net_worth(conn, uid)
    cf = services.cash_flow(conn, uid, month_start, today_str)
    conn.commit()

    conn.close()

    return render_template(
        "dashboard.html",
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        month_expense=month_expense,
        month_income=month_income,
        txns_today=txns_today,
        txns_month=txns_month,
        avg_daily=avg_daily,
        monthly_budget=monthly_budget,
        savings_goal=savings_goal,
        budget_pct=min(budget_pct, 100),
        remaining_budget=remaining_budget,
        recent=recent,
        savings=balance,
        savings_rate=savings_rate,
        net_worth=to_major(nw["net_worth_minor"]),
        assets_total=to_major(nw["assets_minor"]),
        liabilities_total=to_major(nw["liabilities_minor"]),
        cash_flow_month=to_major(cf["income_minor"] - cf["expenses_minor"]),
    )


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------
@app.route("/expenses")
@login_required
def expenses():
    uid = session["user_id"]
    conn = get_db_connection()

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    sort = request.args.get("sort", "newest")

    query = "SELECT * FROM expenses WHERE user_id = ?"
    params = [uid]

    if search:
        query += " AND (description LIKE ? OR category LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if category:
        query += " AND category = ?"
        params.append(category)
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)

    if sort == "oldest":
        query += " ORDER BY date ASC, id ASC"
    elif sort == "amount_high":
        query += " ORDER BY amount DESC"
    elif sort == "amount_low":
        query += " ORDER BY amount ASC"
    else:
        query += " ORDER BY date DESC, id DESC"

    rows = conn.execute(query, params).fetchall()
    categories = conn.execute(
        "SELECT DISTINCT category FROM expenses WHERE user_id = ? ORDER BY category", (uid,)
    ).fetchall()
    conn.close()

    return render_template(
        "expenses.html", expenses=rows, categories=categories,
        search=search, selected_category=category, date_from=date_from,
        date_to=date_to, sort=sort
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    uid = session["user_id"]
    if request.method == "POST":
        category = request.form.get("category")
        custom_category = request.form.get("custom_category", "").strip()
        amount = request.form.get("amount")
        description = request.form.get("description", "").strip()
        date = request.form.get("date")
        payment_mode = request.form.get("payment_mode", "Cash")
        merchant = request.form.get("merchant", "").strip() or None
        conn_cur = get_db_connection()
        user_row = conn_cur.execute("SELECT currency FROM users WHERE id=?", (uid,)).fetchone()
        conn_cur.close()
        currency = request.form.get("currency") or (user_row["currency"] if user_row else DEFAULT_CURRENCY)
        if currency not in CURRENCIES:
            currency = user_row["currency"] if user_row else DEFAULT_CURRENCY

        if category == "Other" and custom_category:
            final_category = custom_category
        else:
            final_category = category

        if not final_category or not amount or not date:
            flash("Category, amount and date are required.", "error")
            return redirect(url_for("add_expense"))

        try:
            amount = float(amount)
            if not (0 < amount < 1e12):
                raise ValueError
        except (ValueError, TypeError):
            flash("Please enter a valid positive amount.", "error")
            return redirect(url_for("add_expense"))

        receipt_path = None
        file = request.files.get("receipt")
        if file and file.filename:
            receipt_path, err = security.save_receipt(file, app.config["RECEIPT_DIR"])
            if err:
                flash(err, "error")
                return redirect(url_for("add_expense"))

        icon = CATEGORY_ICONS.get(category, "fa-receipt")
        amount_minor = to_minor(amount)

        conn = get_db_connection()
        dupes = services.find_possible_duplicate(conn, uid, amount_minor, date, final_category)
        cur = conn.execute(
            """INSERT INTO expenses
               (user_id, category, custom_category, icon, amount, amount_minor, description, date, payment_mode, receipt_path, currency, merchant, txn_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'expense', ?)""",
            (uid, final_category, custom_category, icon, amount, amount_minor, description, date, payment_mode, receipt_path, currency, merchant, now_iso())
        )
        services.record_audit(conn, uid, "expense_created", "expense", cur.lastrowid,
                               {"category": final_category, "amount_minor": amount_minor})
        conn.commit()
        conn.close()

        if dupes:
            flash(f"Expense added. Note: a similar {final_category} expense already exists around this date.", "warning")
        else:
            flash("Expense added successfully!", "success")
        return redirect(url_for("expenses"))

    return render_template("add_expense.html", categories=list(CATEGORY_ICONS.keys()))


@app.route("/expenses/edit/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    uid = session["user_id"]
    conn = get_db_connection()
    expense = conn.execute(
        "SELECT * FROM expenses WHERE id = ? AND user_id = ?", (expense_id, uid)
    ).fetchone()

    if not expense:
        conn.close()
        abort(404)

    if request.method == "POST":
        category = request.form.get("category")
        amount = request.form.get("amount")
        description = request.form.get("description", "").strip()
        date = request.form.get("date")
        payment_mode = request.form.get("payment_mode", "Cash")

        try:
            amount = float(amount)
            if not (0 < amount < 1e12):
                raise ValueError
            datetime.strptime(date or "", "%Y-%m-%d")
        except (ValueError, TypeError):
            conn.close()
            flash("Please enter a valid positive amount and date.", "error")
            return redirect(url_for("edit_expense", expense_id=expense_id))
        if not category:
            conn.close()
            flash("Category is required.", "error")
            return redirect(url_for("edit_expense", expense_id=expense_id))

        icon = CATEGORY_ICONS.get(category, "fa-receipt")
        amount_minor = to_minor(amount)
        conn.execute(
            """UPDATE expenses SET category=?, icon=?, amount=?, amount_minor=?, description=?, date=?, payment_mode=?
               WHERE id=? AND user_id=?""",
            (category, icon, amount, amount_minor, description, date, payment_mode, expense_id, uid)
        )
        services.record_audit(conn, uid, "expense_updated", "expense", expense_id, {"category": category})
        conn.commit()
        conn.close()
        flash("Expense updated successfully!", "success")
        return redirect(url_for("expenses"))

    conn.close()
    return render_template("edit_expense.html", expense=expense, categories=list(CATEGORY_ICONS.keys()))


@app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    uid = session["user_id"]
    conn = get_db_connection()
    row = conn.execute("SELECT category, amount FROM expenses WHERE id=? AND user_id=?", (expense_id, uid)).fetchone()
    conn.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, uid))
    if row:
        services.record_audit(conn, uid, "expense_deleted", "expense", expense_id,
                               {"category": row["category"], "amount": row["amount"]})
    conn.commit()
    conn.close()
    flash("Expense deleted.", "success")
    return redirect(url_for("expenses"))


@app.route("/expenses/refund/<int:expense_id>", methods=["POST"])
@login_required
def refund_expense(expense_id):
    uid = session["user_id"]
    amount = request.form.get("amount")
    date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        conn.close()
        flash("Please enter a valid date.", "error")
        return redirect(url_for("expenses"))
    _, err = services.create_refund(conn, uid, expense_id, amount, date)
    if err:
        flash(err, "error")
    else:
        conn.commit()
        flash("Refund recorded.", "success")
    conn.close()
    return redirect(url_for("expenses"))


@app.route("/expenses/reverse/<int:expense_id>", methods=["POST"])
@login_required
def reverse_expense(expense_id):
    uid = session["user_id"]
    conn = get_db_connection()
    _, err = services.create_reversal(conn, uid, expense_id)
    if err:
        flash(err, "error")
    else:
        conn.commit()
        flash("Transaction reversed. The original stays in your history.", "success")
    conn.close()
    return redirect(url_for("expenses"))


@app.route("/expenses/split/add", methods=["GET", "POST"])
@login_required
def add_split():
    uid = session["user_id"]
    if request.method == "POST":
        merchant = request.form.get("merchant", "").strip()
        date = request.form.get("date")
        payment_mode = request.form.get("payment_mode", "Cash")
        description = request.form.get("description", "").strip()
        categories = request.form.getlist("split_category[]")
        amounts = request.form.getlist("split_amount[]")

        conn = get_db_connection()
        user = conn.execute("SELECT currency FROM users WHERE id=?", (uid,)).fetchone()
        try:
            datetime.strptime(date or "", "%Y-%m-%d")
        except ValueError:
            conn.close()
            flash("Please enter a valid date.", "error")
            return redirect(url_for("add_split"))

        parts = [(c.strip(), a) for c, a in zip(categories, amounts) if c.strip() and a.strip()]
        result, err = services.create_split(conn, uid, merchant, date, payment_mode,
                                             user["currency"] if user else DEFAULT_CURRENCY,
                                             parts, description)
        if err:
            conn.close()
            flash(err, "error")
            return redirect(url_for("add_split"))
        conn.commit()
        conn.close()
        flash(f"Split expense added across {len(parts)} categories.", "success")
        return redirect(url_for("expenses"))

    return render_template("add_split.html", categories=list(CATEGORY_ICONS.keys()))


@app.route("/adjustments/add", methods=["GET", "POST"])
@login_required
def add_adjustment():
    uid = session["user_id"]
    if request.method == "POST":
        category = request.form.get("category", "Adjustment").strip() or "Adjustment"
        amount = request.form.get("amount")
        date = request.form.get("date")
        description = request.form.get("description", "").strip()
        conn = get_db_connection()
        user = conn.execute("SELECT currency FROM users WHERE id=?", (uid,)).fetchone()
        try:
            datetime.strptime(date or "", "%Y-%m-%d")
        except ValueError:
            conn.close()
            flash("Please enter a valid date.", "error")
            return redirect(url_for("add_adjustment"))
        _, err = services.create_adjustment(conn, uid, category, amount, date,
                                             user["currency"] if user else DEFAULT_CURRENCY, description)
        if err:
            conn.close()
            flash(err, "error")
            return redirect(url_for("add_adjustment"))
        conn.commit()
        conn.close()
        flash("Adjustment recorded.", "success")
        return redirect(url_for("expenses"))

    return render_template("add_adjustment.html", categories=list(CATEGORY_ICONS.keys()))


# ---------------------------------------------------------------------------
# Income
# ---------------------------------------------------------------------------
@app.route("/income")
@login_required
def income():
    uid = session["user_id"]
    search = request.args.get("search", "").strip()
    conn = get_db_connection()

    query = "SELECT * FROM income WHERE user_id = ?"
    params = [uid]
    if search:
        query += " AND (source LIKE ? OR description LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    query += " ORDER BY date DESC, id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("income.html", income=rows, search=search)


@app.route("/income/add", methods=["GET", "POST"])
@login_required
def add_income():
    uid = session["user_id"]
    if request.method == "POST":
        source = request.form.get("source", "").strip()
        amount = request.form.get("amount")
        description = request.form.get("description", "").strip()
        date = request.form.get("date")

        if not source or not amount or not date:
            flash("Source, amount and date are required.", "error")
            return redirect(url_for("add_income"))

        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Please enter a valid positive amount.", "error")
            return redirect(url_for("add_income"))

        amount_minor = to_minor(amount)
        conn = get_db_connection()
        cur = conn.execute(
            "INSERT INTO income (user_id, source, amount, amount_minor, description, date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, source, amount, amount_minor, description, date, now_iso())
        )
        services.record_audit(conn, uid, "income_created", "income", cur.lastrowid, {"source": source})
        conn.commit()
        conn.close()
        flash("Income added successfully!", "success")
        return redirect(url_for("income"))

    return render_template("add_income.html")


@app.route("/income/edit/<int:income_id>", methods=["GET", "POST"])
@login_required
def edit_income(income_id):
    uid = session["user_id"]
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM income WHERE id = ? AND user_id = ?", (income_id, uid)).fetchone()
    if not row:
        conn.close()
        abort(404)

    if request.method == "POST":
        source = request.form.get("source", "").strip()
        amount = request.form.get("amount")
        description = request.form.get("description", "").strip()
        date = request.form.get("date")
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            flash("Please enter a valid amount.", "error")
            return redirect(url_for("edit_income", income_id=income_id))

        amount_minor = to_minor(amount)
        conn.execute(
            "UPDATE income SET source=?, amount=?, amount_minor=?, description=?, date=? WHERE id=? AND user_id=?",
            (source, amount, amount_minor, description, date, income_id, uid)
        )
        services.record_audit(conn, uid, "income_updated", "income", income_id, {"source": source})
        conn.commit()
        conn.close()
        flash("Income updated successfully!", "success")
        return redirect(url_for("income"))

    conn.close()
    return render_template("edit_income.html", income=row)


@app.route("/income/delete/<int:income_id>", methods=["POST"])
@login_required
def delete_income(income_id):
    uid = session["user_id"]
    conn = get_db_connection()
    conn.execute("DELETE FROM income WHERE id = ? AND user_id = ?", (income_id, uid))
    services.record_audit(conn, uid, "income_deleted", "income", income_id)
    conn.commit()
    conn.close()
    flash("Income deleted.", "success")
    return redirect(url_for("income"))


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
@app.route("/budget", methods=["GET", "POST"])
@login_required
def budget():
    uid = session["user_id"]
    today = datetime.now()
    conn = get_db_connection()

    if request.method == "POST":
        amount = request.form.get("amount")
        savings_goal = request.form.get("savings_goal", 0)
        try:
            amount = float(amount)
            savings_goal = float(savings_goal or 0)
        except ValueError:
            flash("Please enter valid numbers.", "error")
            return redirect(url_for("budget"))

        existing = conn.execute(
            "SELECT id FROM budget WHERE user_id = ? AND month = ? AND year = ?",
            (uid, today.month, today.year)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE budget SET amount = ?, savings_goal = ? WHERE id = ?",
                (amount, savings_goal, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO budget (user_id, month, year, amount, savings_goal) VALUES (?, ?, ?, ?, ?)",
                (uid, today.month, today.year, amount, savings_goal)
            )
        conn.commit()
        flash("Budget updated successfully!", "success")
        conn.close()
        return redirect(url_for("budget"))

    budget_row = conn.execute(
        "SELECT * FROM budget WHERE user_id = ? AND month = ? AND year = ?",
        (uid, today.month, today.year)
    ).fetchone()

    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    next_month_start = (today.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m-%d")
    spent_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) AS t FROM expenses WHERE user_id=? AND date>=? AND date<?", (uid, month_start, next_month_start)
    ).fetchone()["t"]
    spent = float(to_major(spent_minor))

    recurring = conn.execute(
        "SELECT * FROM recurring_expenses WHERE user_id = ? AND active = 1 ORDER BY next_date ASC", (uid,)
    ).fetchall()

    conn.close()

    budget_amount = budget_row["amount"] if budget_row else 0
    savings_goal = budget_row["savings_goal"] if budget_row else 0
    pct = round((spent / budget_amount) * 100, 1) if budget_amount else 0

    return render_template(
        "budget.html", budget_amount=budget_amount, savings_goal=savings_goal,
        spent=spent, pct=min(pct, 100), remaining=budget_amount - spent,
        recurring=recurring
    )


@app.route("/budget/recurring/add", methods=["POST"])
@login_required
def add_recurring():
    uid = session["user_id"]
    category = request.form.get("category")
    amount = request.form.get("amount")
    description = request.form.get("description", "")
    frequency = request.form.get("frequency", "Monthly")
    next_date = request.form.get("next_date")

    try:
        amount = float(amount)
    except (ValueError, TypeError):
        flash("Please enter a valid amount.", "error")
        return redirect(url_for("budget"))

    conn = get_db_connection()
    conn.execute(
        """INSERT INTO recurring_expenses (user_id, category, amount, description, frequency, next_date, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (uid, category, amount, description, frequency, next_date, now_iso())
    )
    conn.commit()
    conn.close()
    flash("Recurring expense scheduled.", "success")
    return redirect(url_for("budget"))


@app.route("/budget/recurring/delete/<int:rec_id>", methods=["POST"])
@login_required
def delete_recurring(rec_id):
    uid = session["user_id"]
    conn = get_db_connection()
    conn.execute("DELETE FROM recurring_expenses WHERE id = ? AND user_id = ?", (rec_id, uid))
    conn.commit()
    conn.close()
    flash("Recurring expense removed.", "success")
    return redirect(url_for("budget"))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def get_report_dataframe(uid, date_from=None, date_to=None, txn_type=None, category=None):
    """
    Build the export dataset from actual stored transactions. Includes both
    expenses and income (labelled by `type`) so reports reflect real cash
    flow, not expenses alone.
    """
    conn = get_db_connection()
    frames = []

    if txn_type in (None, "", "expense"):
        q = "SELECT date, category, description, payment_mode, amount, 'expense' AS type FROM expenses WHERE user_id = ?"
        params = [uid]
        if date_from:
            q += " AND date >= ?"; params.append(date_from)
        if date_to:
            q += " AND date <= ?"; params.append(date_to)
        if category:
            q += " AND category = ?"; params.append(category)
        frames.extend(dict(r) for r in conn.execute(q, params).fetchall())

    if txn_type in (None, "", "income"):
        q = "SELECT date, source AS category, description, 'Income' AS payment_mode, amount, 'income' AS type FROM income WHERE user_id = ?"
        params = [uid]
        if date_from:
            q += " AND date >= ?"; params.append(date_from)
        if date_to:
            q += " AND date <= ?"; params.append(date_to)
        frames.extend(dict(r) for r in conn.execute(q, params).fetchall())

    conn.close()
    df = pd.DataFrame(frames, columns=["date", "category", "description", "payment_mode", "amount", "type"])
    return df.sort_values("date", ascending=False, kind="stable").reset_index(drop=True) if not df.empty else df


@app.route("/reports")
@login_required
def reports():
    uid = session["user_id"]
    conn = get_db_connection()

    # Monthly totals for the current year (for bar/line charts)
    year = datetime.now().year
    monthly_rows = conn.execute(
        """SELECT strftime('%m', date) AS m, SUM(amount_minor) AS total_minor
           FROM expenses WHERE user_id = ? AND strftime('%Y', date) = ?
           GROUP BY m ORDER BY m""",
        (uid, str(year))
    ).fetchall()
    monthly = [{"m": r["m"], "total": float(to_major(r["total_minor"] or 0))} for r in monthly_rows]

    category_rows = conn.execute(
        """SELECT category, SUM(amount_minor) AS total_minor FROM expenses
           WHERE user_id = ? GROUP BY category ORDER BY total_minor DESC""",
        (uid,)
    ).fetchall()
    category_totals = [{"category": r["category"], "total": float(to_major(r["total_minor"] or 0))} for r in category_rows]

    conn.close()
    return render_template(
        "reports.html", monthly=monthly, category_totals=category_totals, year=year
    )


@app.route("/reports/export/csv")
@login_required
def export_csv():
    uid = session["user_id"]
    df = get_report_dataframe(uid, request.args.get("date_from"), request.args.get("date_to"),
                               request.args.get("type"), request.args.get("category"))
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    mem = io.BytesIO(buf.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True,
                      download_name=f"expense_report_{datetime.now().strftime('%Y%m%d')}.csv")


@app.route("/reports/export/excel")
@login_required
def export_excel():
    uid = session["user_id"]
    df = get_report_dataframe(uid, request.args.get("date_from"), request.args.get("date_to"),
                               request.args.get("type"), request.args.get("category"))
    mem = io.BytesIO()
    with pd.ExcelWriter(mem, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Expenses")
    mem.seek(0)
    return send_file(mem, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      as_attachment=True, download_name=f"expense_report_{datetime.now().strftime('%Y%m%d')}.xlsx")


@app.route("/reports/export/pdf")
@login_required
def export_pdf():
    uid = session["user_id"]
    df = get_report_dataframe(uid, request.args.get("date_from"), request.args.get("date_to"),
                               request.args.get("type"), request.args.get("category"))

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch

    conn_user = get_db_connection()
    user = conn_user.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    symbol = get_user_currency_symbol(user)
    conn_user.close()

    income_total = df[df["type"] == "income"]["amount"].sum() if not df.empty else 0
    expense_total = df[df["type"] == "expense"]["amount"].sum() if not df.empty else 0
    date_from = request.args.get("date_from") or (df["date"].min() if not df.empty else "-")
    date_to = request.args.get("date_to") or (df["date"].max() if not df.empty else "-")

    mem = io.BytesIO()
    doc = SimpleDocTemplate(mem, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [Paragraph("LEDGER", styles["Title"]), Paragraph("Financial Report", styles["Heading2"]),
                Spacer(1, 6),
                Paragraph(f"Period: {date_from} &ndash; {date_to}", styles["Normal"]),
                Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]),
                Spacer(1, 16)]

    summary = [
        ["Income", f"{symbol}{income_total:,.2f}"],
        ["Expenses", f"{symbol}{expense_total:,.2f}"],
        ["Net Cash Flow", f"{symbol}{(income_total - expense_total):,.2f}"],
    ]
    summary_table = Table(summary, colWidths=[2 * inch, 2 * inch])
    summary_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Transaction Detail", styles["Heading3"]))
    elements.append(Spacer(1, 8))

    data = [["Date", "Type", "Category", "Description", "Amount"]]
    for _, row in df.iterrows():
        data.append([
            str(row["date"]), str(row["type"]).capitalize(), str(row["category"]),
            str(row["description"] or "")[:28], f"{row['amount']:.2f}"
        ])
    data.append(["", "", "", "Net", f"{(income_total - expense_total):.2f}"])

    table = Table(data, colWidths=[0.9 * inch, 0.8 * inch, 1.1 * inch, 2.2 * inch, 1 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
    ]))
    elements.append(table)
    doc.build(elements)
    mem.seek(0)
    return send_file(mem, mimetype="application/pdf", as_attachment=True,
                      download_name=f"expense_report_{datetime.now().strftime('%Y%m%d')}.pdf")


# ---------------------------------------------------------------------------
# Settings / Profile
# ---------------------------------------------------------------------------
@app.route("/settings")
@login_required
def settings():
    uid = session["user_id"]
    conn = get_db_connection()
    # The most recent login_success is this session; show the one before it.
    rows = conn.execute(
        "SELECT created_at FROM audit_log WHERE user_id=? AND action='login_success' "
        "ORDER BY id DESC LIMIT 2", (uid,)
    ).fetchall()
    conn.close()
    last_login = rows[1]["created_at"] if len(rows) > 1 else None
    return render_template("settings.html", last_login=last_login)


@app.route("/settings/profile", methods=["POST"])
@login_required
def update_profile():
    uid = session["user_id"]
    name = request.form.get("name", "").strip()
    currency = request.form.get("currency", DEFAULT_CURRENCY)
    language = request.form.get("language", "English")
    if currency not in CURRENCIES:
        currency = DEFAULT_CURRENCY
    if language not in LANGUAGES:
        language = "English"
    if not name:
        flash("Name cannot be empty.", "error")
        return redirect(url_for("settings"))

    conn = get_db_connection()
    conn.execute("UPDATE users SET name = ?, currency = ?, language = ? WHERE id = ?",
                 (name, currency, language, uid))
    conn.execute("UPDATE settings SET currency = ?, language = ? WHERE user_id = ?",
                 (currency, language, uid))
    conn.commit()
    conn.close()
    session["user_name"] = name
    flash("Profile updated successfully!", "success")
    return redirect(url_for("settings"))


@app.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    uid = session["user_id"]
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    if not check_password_hash(user["password_hash"], current):
        conn.close()
        flash("Current password is incorrect.", "error")
        return redirect(url_for("settings"))
    pw_error = security.validate_password(new)
    if pw_error:
        conn.close()
        flash(pw_error, "error")
        return redirect(url_for("settings"))
    if new != confirm:
        conn.close()
        flash("New passwords do not match.", "error")
        return redirect(url_for("settings"))

    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (generate_password_hash(new), uid))
    conn.commit()
    conn.close()
    log.info("password_changed user_id=%s", uid)
    flash("Password changed successfully!", "success")
    return redirect(url_for("settings"))


@app.route("/settings/theme", methods=["POST"])
@login_required
def toggle_theme():
    uid = session["user_id"]
    dark_mode = 1 if request.json.get("dark_mode") else 0
    conn = get_db_connection()
    conn.execute("UPDATE users SET dark_mode = ? WHERE id = ?", (dark_mode, uid))
    conn.execute("UPDATE settings SET dark_mode = ? WHERE user_id = ?", (dark_mode, uid))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/settings/delete-account", methods=["POST"])
@login_required
def delete_account():
    uid = session["user_id"]
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], request.form.get("password", "")):
        conn.close()
        flash("Password is incorrect. Account was not deleted.", "error")
        return redirect(url_for("settings"))

    receipts = [r["receipt_path"] for r in conn.execute(
        "SELECT receipt_path FROM expenses WHERE user_id = ? AND receipt_path IS NOT NULL", (uid,)
    ).fetchall()]
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    for rp in receipts:
        path = resolve_receipt_path(rp)
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                log.warning("receipt_cleanup_failed user_id=%s", uid)
    log.info("account_deleted user_id=%s", uid)
    session.clear()
    flash("Your account has been deleted.", "success")
    return redirect(url_for("index"))


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html")


# ---------------------------------------------------------------------------
# JSON APIs (charts, live search)
# ---------------------------------------------------------------------------
@app.route("/api/chart-data")
@login_required
def api_chart_data():
    uid = session["user_id"]
    conn = get_db_connection()

    # Category breakdown (pie)
    cat_rows = conn.execute(
        "SELECT category, SUM(amount_minor) AS total_minor FROM expenses WHERE user_id = ? GROUP BY category",
        (uid,)
    ).fetchall()
    cat_rows = [{"category": r["category"], "total": float(to_major(r["total_minor"] or 0))} for r in cat_rows]

    # Last 30 days trend (line/area)
    start = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
    trend_rows = conn.execute(
        "SELECT date, SUM(amount_minor) AS total_minor FROM expenses WHERE user_id = ? AND date >= ? GROUP BY date ORDER BY date",
        (uid, start)
    ).fetchall()
    trend_map = {r["date"]: float(to_major(r["total_minor"] or 0)) for r in trend_rows}
    trend_labels, trend_values = [], []
    for i in range(30):
        d = (datetime.now() - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        trend_labels.append(d[5:])
        trend_values.append(round(trend_map.get(d, 0), 2))

    # Income vs Expense monthly (current year)
    year = datetime.now().year
    inc_rows = conn.execute(
        "SELECT strftime('%m', date) AS m, SUM(amount_minor) AS total_minor FROM income WHERE user_id=? AND strftime('%Y',date)=? GROUP BY m",
        (uid, str(year))
    ).fetchall()
    exp_rows = conn.execute(
        "SELECT strftime('%m', date) AS m, SUM(amount_minor) AS total_minor FROM expenses WHERE user_id=? AND strftime('%Y',date)=? GROUP BY m",
        (uid, str(year))
    ).fetchall()
    inc_map = {r["m"]: float(to_major(r["total_minor"] or 0)) for r in inc_rows}
    exp_map = {r["m"]: float(to_major(r["total_minor"] or 0)) for r in exp_rows}
    months = [calendar.month_abbr[i] for i in range(1, 13)]
    income_series = [round(inc_map.get(f"{i:02d}", 0), 2) for i in range(1, 13)]
    expense_series = [round(exp_map.get(f"{i:02d}", 0), 2) for i in range(1, 13)]

    # Weekly spending heatmap (day of week totals, last 12 weeks)
    heat_start = (datetime.now() - timedelta(weeks=12)).strftime("%Y-%m-%d")
    heat_rows = conn.execute(
        "SELECT date, amount_minor FROM expenses WHERE user_id = ? AND date >= ?", (uid, heat_start)
    ).fetchall()
    dow_minor = [0] * 7
    for r in heat_rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
            dow_minor[d.weekday()] += r["amount_minor"] or 0
        except ValueError:
            pass
    dow_totals = [float(to_major(m)) for m in dow_minor]

    conn.close()

    return jsonify({
        "category_labels": [r["category"] for r in cat_rows],
        "category_values": [round(r["total"], 2) for r in cat_rows],
        "trend_labels": trend_labels,
        "trend_values": trend_values,
        "months": months,
        "income_series": income_series,
        "expense_series": expense_series,
        "dow_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "dow_values": [round(v, 2) for v in dow_totals],
    })


@app.route("/api/search")
@login_required
def api_search():
    uid = session["user_id"]
    q = request.args.get("q", "").strip()
    conn = get_db_connection()
    results = []
    if q:
        rows = conn.execute(
            """SELECT id, category, description, amount, date FROM expenses
               WHERE user_id = ? AND (category LIKE ? OR description LIKE ? OR CAST(amount AS TEXT) LIKE ?)
               ORDER BY date DESC LIMIT 10""",
            (uid, f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
        results = [dict(r) for r in rows]
    conn.close()
    return jsonify(results)


@app.route("/api/insights")
@login_required
def api_insights():
    """
    Rule-based spending insights. Anomaly detection compares each expense to
    its OWN category's history (mean of same-category spend), not a single
    global average, and explains why a transaction was flagged (see #29).
    """
    uid = session["user_id"]
    conn = get_db_connection()

    cat_rows = conn.execute(
        "SELECT category, SUM(amount_minor) AS total_minor, COUNT(*) AS c FROM expenses "
        "WHERE user_id=? GROUP BY category ORDER BY total_minor DESC LIMIT 3",
        (uid,)
    ).fetchall()
    cat_rows = [{"category": r["category"], "total": float(to_major(r["total_minor"] or 0)), "c": r["c"]} for r in cat_rows]

    # Per-category mean, using only categories with enough history to judge.
    stats_rows = conn.execute(
        "SELECT category, AVG(amount_minor) AS avg_minor, COUNT(*) AS n FROM expenses "
        "WHERE user_id=? GROUP BY category HAVING n >= 3",
        (uid,)
    ).fetchall()
    stats = {r["category"]: r["avg_minor"] for r in stats_rows}

    unusual = []
    if stats:
        all_recent = conn.execute(
            "SELECT id, category, amount, amount_minor, date FROM expenses WHERE user_id=? "
            "ORDER BY date DESC LIMIT 200", (uid,)
        ).fetchall()
        for r in all_recent:
            cat_avg = stats.get(r["category"])
            if cat_avg and r["amount_minor"] > cat_avg * 3:
                unusual.append({
                    "category": r["category"], "amount": r["amount"], "date": r["date"],
                    "reason": f"This is significantly higher than your typical {r['category']} transactions "
                              f"(about {round(r['amount_minor'] / cat_avg, 1)}x your usual amount in this category).",
                })
            if len(unusual) >= 5:
                break

    conn.close()

    suggestions = []
    if cat_rows:
        top = cat_rows[0]
        suggestions.append(f"Your highest spending category is {top['category']} — consider setting a category-specific limit.")
    if unusual:
        suggestions.append(f"We noticed {len(unusual)} unusually large transaction(s) compared to your own history in that category.")
    if not suggestions:
        suggestions.append("Keep adding transactions to unlock personalized spending insights.")

    return jsonify({
        "top_categories": cat_rows,
        "unusual_transactions": unusual,
        "suggestions": suggestions,
    })


# ---------------------------------------------------------------------------
# Accounts & Transfers
# ---------------------------------------------------------------------------
@app.route("/accounts", methods=["GET", "POST"])
@login_required
def accounts():
    uid = session["user_id"]
    conn = get_db_connection()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        acc_type = request.form.get("type", "Other")
        opening = request.form.get("opening_balance", "0")
        notes = request.form.get("notes", "").strip()
        user = conn.execute("SELECT currency FROM users WHERE id=?", (uid,)).fetchone()
        if not name or acc_type not in services.ACCOUNT_TYPES:
            flash("Please provide a name and a valid account type.", "error")
        else:
            try:
                to_minor(opening)
            except Exception:
                flash("Opening balance must be a number.", "error")
                conn.close()
                return redirect(url_for("accounts"))
            services.create_account(conn, uid, name, acc_type, opening, user["currency"], notes)
            conn.commit()
            flash("Account added.", "success")
        return redirect(url_for("accounts"))

    rows = conn.execute("SELECT * FROM accounts WHERE user_id=? AND status='active' ORDER BY created_at", (uid,)).fetchall()
    symbol = get_user_currency_symbol(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    conn.close()
    return render_template("accounts.html", accounts=rows, account_types=services.ACCOUNT_TYPES,
                            currency_symbol=symbol, to_major=to_major)


@app.route("/accounts/archive/<int:account_id>", methods=["POST"])
@login_required
def archive_account_route(account_id):
    uid = session["user_id"]
    conn = get_db_connection()
    services.archive_account(conn, uid, account_id)
    conn.commit()
    conn.close()
    flash("Account archived.", "success")
    return redirect(url_for("accounts"))


@app.route("/transfers/add", methods=["POST"])
@login_required
def add_transfer():
    uid = session["user_id"]
    from_id = request.form.get("from_account_id", type=int)
    to_id = request.form.get("to_account_id", type=int)
    amount = request.form.get("amount")
    date = request.form.get("date")
    note = request.form.get("note", "").strip()
    conn = get_db_connection()
    try:
        to_minor(amount)
        datetime.strptime(date or "", "%Y-%m-%d")
    except Exception:
        conn.close()
        flash("Please provide a valid amount and date.", "error")
        return redirect(url_for("accounts"))
    _, err = services.create_transfer(conn, uid, from_id, to_id, amount, date, note)
    if err:
        flash(err, "error")
    else:
        conn.commit()
        flash("Transfer completed.", "success")
    conn.close()
    return redirect(url_for("accounts"))


@app.route("/statements")
@login_required
def statements():
    uid = session["user_id"]
    today = datetime.now()
    date_from = request.args.get("date_from") or today.replace(day=1).strftime("%Y-%m-%d")
    date_to = request.args.get("date_to") or today.strftime("%Y-%m-%d")
    conn = get_db_connection()
    inc_stmt = services.income_statement(conn, uid, date_from, date_to)
    bs = services.balance_sheet(conn, uid)
    cfs = services.cash_flow_statement(conn, uid, date_from, date_to)
    conn.close()
    return render_template("statements.html", date_from=date_from, date_to=date_to,
                            inc=inc_stmt, bs=bs, cfs=cfs, to_major=to_major)


@app.route("/net-worth")
@login_required
def net_worth_page():
    uid = session["user_id"]
    conn = get_db_connection()
    accts = conn.execute("SELECT * FROM accounts WHERE user_id=? AND status='active'", (uid,)).fetchall()
    nw = services.net_worth(conn, uid)
    today = datetime.now()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    cf = services.cash_flow(conn, uid, month_start, today.strftime("%Y-%m-%d"))
    symbol = get_user_currency_symbol(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    conn.close()
    return render_template("net_worth.html", accounts=accts, nw=nw, cf=cf,
                            currency_symbol=symbol, to_major=to_major)


@app.route("/accounts/reconcile/<int:account_id>", methods=["GET", "POST"])
@login_required
def reconcile_account(account_id):
    uid = session["user_id"]
    conn = get_db_connection()
    account = conn.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (account_id, uid)).fetchone()
    if not account:
        conn.close()
        abort(404)

    statement_balance = None
    difference = None
    if request.method == "POST":
        raw = request.form.get("statement_balance", "")
        try:
            statement_minor = to_minor(raw)
            statement_balance = to_major(statement_minor)
            difference = to_major(account["balance_minor"] - statement_minor)
            services.record_audit(conn, uid, "account_reconciled", "account", account_id,
                                   {"statement_balance": str(statement_balance), "difference": str(difference)})
            conn.commit()
        except Exception:
            flash("Please enter a valid statement balance.", "error")

    symbol = get_user_currency_symbol(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    conn.close()
    return render_template("reconcile.html", account=account, statement_balance=statement_balance,
                            difference=difference, currency_symbol=symbol, to_major=to_major)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
@app.route("/goals", methods=["GET", "POST"])
@login_required
def goals():
    uid = session["user_id"]
    conn = get_db_connection()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        target = request.form.get("target")
        target_date = request.form.get("target_date") or None
        priority = request.form.get("priority", "medium")
        try:
            target_minor = to_minor(target)
            if target_minor <= 0:
                raise ValueError
        except Exception:
            flash("Please enter a valid target amount.", "error")
            conn.close()
            return redirect(url_for("goals"))
        if not name:
            flash("Goal name is required.", "error")
            conn.close()
            return redirect(url_for("goals"))
        conn.execute(
            "INSERT INTO goals (user_id, name, target_minor, saved_minor, target_date, priority, status, created_at) "
            "VALUES (?, ?, ?, 0, ?, ?, 'active', ?)",
            (uid, name, target_minor, target_date, priority, now_iso()),
        )
        services.record_audit(conn, uid, "goal_created", "goal", None, {"name": name})
        conn.commit()
        flash("Goal added.", "success")
        return redirect(url_for("goals"))

    rows = conn.execute("SELECT * FROM goals WHERE user_id=? AND status='active' ORDER BY created_at", (uid,)).fetchall()
    today = datetime.now().date()
    enriched = []
    for g in rows:
        remaining_minor = g["target_minor"] - g["saved_minor"]
        months_left = None
        required_monthly = None
        if g["target_date"]:
            try:
                td = datetime.strptime(g["target_date"], "%Y-%m-%d").date()
                months_left = max(1, (td.year - today.year) * 12 + (td.month - today.month))
                required_monthly = to_major(round(max(0, remaining_minor) / months_left))
            except ValueError:
                pass
        enriched.append({
            "row": g,
            "saved": to_major(g["saved_minor"]),
            "target": to_major(g["target_minor"]),
            "remaining": to_major(max(0, remaining_minor)),
            "progress_pct": min(100, round(g["saved_minor"] / g["target_minor"] * 100)) if g["target_minor"] else 0,
            "required_monthly": required_monthly,
        })
    symbol = get_user_currency_symbol(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    conn.close()
    return render_template("goals.html", goals=enriched, currency_symbol=symbol)


@app.route("/goals/contribute/<int:goal_id>", methods=["POST"])
@login_required
def contribute_goal(goal_id):
    uid = session["user_id"]
    amount = request.form.get("amount")
    conn = get_db_connection()
    goal = conn.execute("SELECT * FROM goals WHERE id=? AND user_id=?", (goal_id, uid)).fetchone()
    if not goal:
        conn.close()
        abort(404)
    try:
        amount_minor = to_minor(amount)
        if amount_minor <= 0:
            raise ValueError
    except Exception:
        conn.close()
        flash("Please enter a valid contribution amount.", "error")
        return redirect(url_for("goals"))
    new_saved = goal["saved_minor"] + amount_minor
    status = "completed" if new_saved >= goal["target_minor"] else "active"
    conn.execute("UPDATE goals SET saved_minor=?, status=? WHERE id=?", (new_saved, status, goal_id))
    conn.execute("INSERT INTO goal_contributions (goal_id, amount_minor, date, created_at) VALUES (?, ?, ?, ?)",
                 (goal_id, amount_minor, datetime.now().strftime("%Y-%m-%d"), now_iso()))
    services.record_audit(conn, uid, "goal_contribution", "goal", goal_id, {"amount_minor": amount_minor})
    conn.commit()
    conn.close()
    flash("Contribution recorded. Estimated completion depends on your future saving rate.", "success")
    return redirect(url_for("goals"))


# ---------------------------------------------------------------------------
# Subscriptions (a filtered, calculated view over recurring expenses)
# ---------------------------------------------------------------------------
@app.route("/subscriptions")
@login_required
def subscriptions():
    uid = session["user_id"]
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM recurring_expenses WHERE user_id=? AND active=1 ORDER BY next_date", (uid,)
    ).fetchall()
    monthly_total = 0.0
    items = []
    for r in rows:
        freq = (r["frequency"] or "monthly").lower()
        monthly_equiv = r["amount"]
        if freq == "weekly":
            monthly_equiv = r["amount"] * 52 / 12
        elif freq == "yearly":
            monthly_equiv = r["amount"] / 12
        monthly_total += monthly_equiv
        items.append({"row": r, "monthly_equiv": round(monthly_equiv, 2)})
    symbol = get_user_currency_symbol(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    conn.close()
    return render_template("subscriptions.html", items=items, monthly_total=round(monthly_total, 2),
                            yearly_total=round(monthly_total * 12, 2), currency_symbol=symbol)


# ---------------------------------------------------------------------------
# Data Quality Center
# ---------------------------------------------------------------------------
@app.route("/data-quality")
@login_required
def data_quality():
    uid = session["user_id"]
    conn = get_db_connection()
    uncategorized = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? AND (category IS NULL OR category='') ORDER BY date DESC", (uid,)
    ).fetchall()
    no_account = conn.execute(
        "SELECT * FROM expenses WHERE user_id=? AND account_id IS NULL ORDER BY date DESC LIMIT 50", (uid,)
    ).fetchall()
    all_expenses = conn.execute("SELECT * FROM expenses WHERE user_id=? ORDER BY date", (uid,)).fetchall()
    seen = {}
    duplicates = []
    for e in all_expenses:
        key = (e["amount_minor"], e["category"], e["date"])
        if key in seen:
            duplicates.append(e)
        else:
            seen[key] = e["id"]
    conn.close()
    return render_template("data_quality.html", uncategorized=uncategorized,
                            no_account=no_account, duplicates=duplicates)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
@app.route("/audit-log")
@login_required
def audit_log_page():
    uid = session["user_id"]
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT 200", (uid,)
    ).fetchall()
    conn.close()
    return render_template("audit_log.html", entries=rows)


# ---------------------------------------------------------------------------
# API v1 - authenticated, user-scoped, rate-limited, paginated
# ---------------------------------------------------------------------------
def api_error(message, status=400, code=None):
    return jsonify({"error": {"code": code or status, "message": message}}), status


def api_rate_limited(f):
    from functools import wraps

    @wraps(f)
    def wrapped(*args, **kwargs):
        key = session.get("user_id", client_ip())
        if not api_limiter.allow(key):
            return api_error("Rate limit exceeded. Please slow down.", 429, "rate_limited")
        return f(*args, **kwargs)
    return wrapped


def paginate_args():
    limit = min(max(request.args.get("limit", 50, type=int) or 50, 1), 100)
    offset = max(request.args.get("offset", 0, type=int) or 0, 0)
    return limit, offset


def expense_to_json(r):
    return {
        "id": r["id"], "category": r["category"], "amount": r["amount"],
        "currency": r["currency"], "date": r["date"], "payment_mode": r["payment_mode"],
        "description": r["description"], "merchant": r["merchant"], "txn_type": r["txn_type"],
    }


@app.route("/api/v1/expenses", methods=["GET", "POST"])
@login_required
@api_rate_limited
def api_v1_expenses():
    uid = session["user_id"]
    repo = repositories.ExpenseRepository()
    try:
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            category = body.get("category")
            amount = body.get("amount")
            date = body.get("date")
            if not category or amount is None or not date:
                return api_error("category, amount and date are required.", 422, "validation_error")
            try:
                amount_minor = to_minor(amount)
                if amount_minor <= 0:
                    raise ValueError
                datetime.strptime(date, "%Y-%m-%d")
            except (ValueError, TypeError):
                return api_error("amount must be positive and date must be YYYY-MM-DD.", 422, "validation_error")
            user = repo.conn.execute("SELECT currency FROM users WHERE id=?", (uid,)).fetchone()
            new_id = repo.create(
                uid, category=category, custom_category=body.get("custom_category"),
                icon=CATEGORY_ICONS.get(category, "fa-receipt"), amount=float(to_major(amount_minor)),
                amount_minor=amount_minor, description=body.get("description", ""), date=date,
                payment_mode=body.get("payment_mode", "Cash"), currency=user["currency"],
                merchant=body.get("merchant"), txn_type="expense",
            )
            services.record_audit(repo.conn, uid, "expense_created", "expense", new_id, {"via": "api"})
            repo.conn.commit()
            row = repo.get(new_id, uid)
            return jsonify(expense_to_json(row)), 201

        limit, offset = paginate_args()
        rows = repo.list(uid, limit=limit, offset=offset, category=request.args.get("category"),
                          date_from=request.args.get("date_from"), date_to=request.args.get("date_to"))
        total = repo.count(uid, category=request.args.get("category"),
                            date_from=request.args.get("date_from"), date_to=request.args.get("date_to"))
        return jsonify({"data": [expense_to_json(r) for r in rows], "limit": limit, "offset": offset, "total": total})
    finally:
        repo.close()


@app.route("/api/v1/expenses/<int:expense_id>", methods=["GET", "PUT", "DELETE"])
@login_required
@api_rate_limited
def api_v1_expense_detail(expense_id):
    uid = session["user_id"]
    repo = repositories.ExpenseRepository()
    try:
        row = repo.get(expense_id, uid)
        if not row:
            return api_error("Expense not found.", 404, "not_found")

        if request.method == "GET":
            return jsonify(expense_to_json(row))

        if request.method == "DELETE":
            repo.hard_delete(expense_id, uid)
            services.record_audit(repo.conn, uid, "expense_deleted", "expense", expense_id, {"via": "api"})
            repo.conn.commit()
            return "", 204

        body = request.get_json(silent=True) or {}
        updates = {}
        if "category" in body:
            updates["category"] = body["category"]
            updates["icon"] = CATEGORY_ICONS.get(body["category"], "fa-receipt")
        if "amount" in body:
            try:
                amount_minor = to_minor(body["amount"])
                if amount_minor <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                return api_error("amount must be a positive number.", 422, "validation_error")
            updates["amount"] = float(to_major(amount_minor))
            updates["amount_minor"] = amount_minor
        if "date" in body:
            try:
                datetime.strptime(body["date"], "%Y-%m-%d")
            except (ValueError, TypeError):
                return api_error("date must be YYYY-MM-DD.", 422, "validation_error")
            updates["date"] = body["date"]
        for field in ("description", "payment_mode", "merchant"):
            if field in body:
                updates[field] = body[field]
        if not updates:
            return api_error("No valid fields to update.", 422, "validation_error")

        repo.update(expense_id, uid, **updates)
        services.record_audit(repo.conn, uid, "expense_updated", "expense", expense_id, {"via": "api"})
        repo.conn.commit()
        return jsonify(expense_to_json(repo.get(expense_id, uid)))
    finally:
        repo.close()


@app.route("/api/v1/income", methods=["GET", "POST"])
@login_required
@api_rate_limited
def api_v1_income():
    uid = session["user_id"]
    repo = repositories.IncomeRepository()
    try:
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            source = body.get("source")
            amount = body.get("amount")
            date = body.get("date")
            if not source or amount is None or not date:
                return api_error("source, amount and date are required.", 422, "validation_error")
            try:
                amount_minor = to_minor(amount)
                if amount_minor <= 0:
                    raise ValueError
                datetime.strptime(date, "%Y-%m-%d")
            except (ValueError, TypeError):
                return api_error("amount must be positive and date must be YYYY-MM-DD.", 422, "validation_error")
            cur = repo.conn.execute(
                "INSERT INTO income (user_id, source, amount, amount_minor, description, date, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, source, float(to_major(amount_minor)), amount_minor, body.get("description", ""), date, now_iso()),
            )
            services.record_audit(repo.conn, uid, "income_created", "income", cur.lastrowid, {"via": "api"})
            repo.conn.commit()
            row = repo.get(cur.lastrowid, uid)
            return jsonify(dict(row)), 201

        limit, offset = paginate_args()
        rows = repo.list(uid, limit=limit, offset=offset, date_from=request.args.get("date_from"),
                          date_to=request.args.get("date_to"))
        return jsonify({"data": [dict(r) for r in rows], "limit": limit, "offset": offset})
    finally:
        repo.close()


@app.route("/api/v1/accounts", methods=["GET", "POST"])
@login_required
@api_rate_limited
def api_v1_accounts():
    uid = session["user_id"]
    repo = repositories.AccountRepository()
    try:
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            name = body.get("name")
            acc_type = body.get("type")
            if not name or acc_type not in services.ACCOUNT_TYPES:
                return api_error(f"name is required and type must be one of {services.ACCOUNT_TYPES}.",
                                  422, "validation_error")
            user = repo.conn.execute("SELECT currency FROM users WHERE id=?", (uid,)).fetchone()
            try:
                new_id = services.create_account(repo.conn, uid, name, acc_type,
                                                  body.get("opening_balance", 0), user["currency"], body.get("notes"))
            except Exception:
                return api_error("Invalid opening_balance.", 422, "validation_error")
            repo.conn.commit()
            row = repo.get(new_id, uid)
            return jsonify({"id": row["id"], "name": row["name"], "type": row["type"],
                             "balance": str(to_major(row["balance_minor"]))}), 201

        rows = repo.list(uid)
        return jsonify([{
            "id": r["id"], "name": r["name"], "type": r["type"],
            "balance": str(to_major(r["balance_minor"])), "currency": r["currency"],
            "is_liability": bool(r["is_liability"]),
        } for r in rows])
    finally:
        repo.close()


@app.route("/api/v1/net-worth")
@login_required
@api_rate_limited
def api_v1_net_worth():
    uid = session["user_id"]
    conn = get_db_connection()
    nw = services.net_worth(conn, uid)
    conn.close()
    return jsonify({k: str(to_major(v)) for k, v in nw.items()})


@app.route("/api/v1/budgets")
@login_required
@api_rate_limited
def api_v1_budgets():
    uid = session["user_id"]
    conn = get_db_connection()
    rows = conn.execute("SELECT month, year, monthly_budget, savings_goal FROM budget WHERE user_id=?", (uid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/v1/goals")
@login_required
@api_rate_limited
def api_v1_goals():
    uid = session["user_id"]
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM goals WHERE user_id=? AND status='active'", (uid,)).fetchall()
    conn.close()
    return jsonify([{
        "id": r["id"], "name": r["name"], "target": str(to_major(r["target_minor"])),
        "saved": str(to_major(r["saved_minor"])), "target_date": r["target_date"], "status": r["status"],
    } for r in rows])


@app.route("/api/v1/transactions")
@login_required
@api_rate_limited
def api_v1_transactions():
    uid = session["user_id"]
    limit, offset = paginate_args()
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, category, amount, date, payment_mode, description FROM expenses "
        "WHERE user_id=? AND is_deleted=0 ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
        (uid, limit, offset),
    ).fetchall()
    conn.close()
    return jsonify({"transactions": [dict(r) for r in rows], "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# Receipts (authenticated, never public)
# ---------------------------------------------------------------------------
def resolve_receipt_path(stored):
    """Map a stored receipt_path to a safe absolute path, or None."""
    if not stored:
        return None
    name = os.path.basename(stored)
    if stored.startswith("receipts/"):
        base = app.config["RECEIPT_DIR"]
    elif stored.startswith("uploads/"):  # files saved by the pre-upgrade version
        base = app.config["LEGACY_UPLOAD_DIR"]
    else:
        return None
    path = os.path.realpath(os.path.join(base, name))
    return path if path.startswith(os.path.realpath(base) + os.sep) else None


@app.route("/receipts/<int:expense_id>")
@login_required
def receipt(expense_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT receipt_path FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, session["user_id"])
    ).fetchone()
    conn.close()
    path = resolve_receipt_path(row["receipt_path"]) if row else None
    if not path or not os.path.isfile(path):
        abort(404)
    ext = path.rsplit(".", 1)[-1].lower()
    return send_from_directory(
        os.path.dirname(path), os.path.basename(path),
        mimetype=security.RECEIPT_MIME.get(ext, "application/octet-stream"),
        as_attachment=request.args.get("download") == "1",
    )


@app.route("/health")
def health():
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception:
        return jsonify({"status": "error"}), 503
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
def render_error(code, title, message):
    return render_template("error.html", code=code, title=title, message=message), code


@app.errorhandler(400)
def bad_request(e):
    return render_error(400, "Request could not be verified", getattr(e, "description", "Bad request."))


@app.errorhandler(403)
def forbidden(e):
    return render_error(403, "Access denied", "You don't have permission to view this page.")


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(e):
    flash("File is too large. Maximum size is 5 MB.", "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.errorhandler(429)
def too_many(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": {"code": "rate_limited", "message": "Too many requests."}}), 429
    return render_error(429, "Too many requests", "Please slow down and try again shortly.")


@app.errorhandler(500)
def server_error(e):
    log.exception("unhandled_error")
    return render_error(500, "Something went wrong", "An unexpected error occurred. It has been logged.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    backfill_minor_units()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
else:
    init_db()
    backfill_minor_units()
