"""
app.py
Main Flask application for the Expense Tracker.
Handles authentication, expenses, income, budget, reports, settings and APIs
that power the dashboard charts and live search.
"""

import os
import io
import csv
import calendar
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_file, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd

from database import get_db_connection, init_db, now_iso

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production-8f3a1c")
app.config["UPLOAD_FOLDER"] = os.path.join("static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB max upload
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}

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


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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
        return "$"
    return CURRENCIES.get(user["currency"], "$")


@app.context_processor
def inject_globals():
    """Make user info and helpers available to every template."""
    user = get_current_user()
    return dict(
        current_user=user,
        currency_symbol=get_user_currency_symbol(user),
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
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
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
            "INSERT INTO settings (user_id, currency, language, dark_mode) VALUES (?, 'USD', 'English', 0)",
            (user_id,)
        )
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

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
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

    total_income = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM income WHERE user_id = ?", (uid,)
    ).fetchone()["t"]
    total_expense = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM expenses WHERE user_id = ?", (uid,)
    ).fetchone()["t"]
    balance = total_income - total_expense

    month_expense = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM expenses WHERE user_id = ? AND date >= ?",
        (uid, month_start)
    ).fetchone()["t"]
    month_income = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM income WHERE user_id = ? AND date >= ?",
        (uid, month_start)
    ).fetchone()["t"]

    txns_today = conn.execute(
        "SELECT COUNT(*) AS c FROM expenses WHERE user_id = ? AND date = ?", (uid, today_str)
    ).fetchone()["c"]
    txns_month = conn.execute(
        "SELECT COUNT(*) AS c FROM expenses WHERE user_id = ? AND date >= ?", (uid, month_start)
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

    # Financial health score: simple heuristic out of 100
    savings_rate = ((total_income - total_expense) / total_income * 100) if total_income else 0
    budget_score = max(0, 100 - budget_pct) if monthly_budget else 50
    health_score = int(max(0, min(100, (savings_rate * 0.6) + (budget_score * 0.4))))

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
        health_score=health_score,
        savings=balance,
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

        if category == "Other" and custom_category:
            final_category = custom_category
        else:
            final_category = category

        if not final_category or not amount or not date:
            flash("Category, amount and date are required.", "error")
            return redirect(url_for("add_expense"))

        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Please enter a valid positive amount.", "error")
            return redirect(url_for("add_expense"))

        receipt_path = None
        file = request.files.get("receipt")
        if file and file.filename and allowed_file(file.filename):
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            filename = secure_filename(f"{uid}_{int(datetime.now().timestamp())}_{file.filename}")
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            receipt_path = f"uploads/{filename}"

        icon = CATEGORY_ICONS.get(category, "fa-receipt")

        conn = get_db_connection()
        conn.execute(
            """INSERT INTO expenses
               (user_id, category, custom_category, icon, amount, description, date, payment_mode, receipt_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, final_category, custom_category, icon, amount, description, date, payment_mode, receipt_path, now_iso())
        )
        conn.commit()
        conn.close()

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
        except (ValueError, TypeError):
            flash("Please enter a valid amount.", "error")
            return redirect(url_for("edit_expense", expense_id=expense_id))

        icon = CATEGORY_ICONS.get(category, "fa-receipt")
        conn.execute(
            """UPDATE expenses SET category=?, icon=?, amount=?, description=?, date=?, payment_mode=?
               WHERE id=? AND user_id=?""",
            (category, icon, amount, description, date, payment_mode, expense_id, uid)
        )
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
    conn.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, uid))
    conn.commit()
    conn.close()
    flash("Expense deleted.", "success")
    return redirect(url_for("expenses"))


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

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO income (user_id, source, amount, description, date, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, source, amount, description, date, now_iso())
        )
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

        conn.execute(
            "UPDATE income SET source=?, amount=?, description=?, date=? WHERE id=? AND user_id=?",
            (source, amount, description, date, income_id, uid)
        )
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
    spent = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE user_id=? AND date>=?", (uid, month_start)
    ).fetchone()["t"]

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
def get_report_dataframe(uid, date_from=None, date_to=None):
    conn = get_db_connection()
    query = "SELECT date, category, description, payment_mode, amount FROM expenses WHERE user_id = ?"
    params = [uid]
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    query += " ORDER BY date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return pd.DataFrame([dict(r) for r in rows])


@app.route("/reports")
@login_required
def reports():
    uid = session["user_id"]
    conn = get_db_connection()

    # Monthly totals for the current year (for bar/line charts)
    year = datetime.now().year
    monthly = conn.execute(
        """SELECT strftime('%m', date) AS m, SUM(amount) AS total
           FROM expenses WHERE user_id = ? AND strftime('%Y', date) = ?
           GROUP BY m ORDER BY m""",
        (uid, str(year))
    ).fetchall()

    category_totals = conn.execute(
        """SELECT category, SUM(amount) AS total FROM expenses
           WHERE user_id = ? GROUP BY category ORDER BY total DESC""",
        (uid,)
    ).fetchall()

    conn.close()
    return render_template(
        "reports.html", monthly=monthly, category_totals=category_totals, year=year
    )


@app.route("/reports/export/csv")
@login_required
def export_csv():
    uid = session["user_id"]
    df = get_report_dataframe(uid, request.args.get("date_from"), request.args.get("date_to"))
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
    df = get_report_dataframe(uid, request.args.get("date_from"), request.args.get("date_to"))
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
    df = get_report_dataframe(uid, request.args.get("date_from"), request.args.get("date_to"))

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch

    mem = io.BytesIO()
    doc = SimpleDocTemplate(mem, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [Paragraph("Expense Report", styles["Title"]), Spacer(1, 12)]
    elements.append(Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    data = [["Date", "Category", "Description", "Payment", "Amount"]]
    for _, row in df.iterrows():
        data.append([
            str(row["date"]), str(row["category"]), str(row["description"] or "")[:30],
            str(row["payment_mode"]), f"{row['amount']:.2f}"
        ])
    total = df["amount"].sum() if not df.empty else 0
    data.append(["", "", "", "Total", f"{total:.2f}"])

    table = Table(data, colWidths=[1 * inch, 1.2 * inch, 2.2 * inch, 1.1 * inch, 1 * inch])
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
    return render_template("settings.html")


@app.route("/settings/profile", methods=["POST"])
@login_required
def update_profile():
    uid = session["user_id"]
    name = request.form.get("name", "").strip()
    currency = request.form.get("currency", "USD")
    language = request.form.get("language", "English")

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
    if len(new) < 6:
        conn.close()
        flash("New password must be at least 6 characters.", "error")
        return redirect(url_for("settings"))
    if new != confirm:
        conn.close()
        flash("New passwords do not match.", "error")
        return redirect(url_for("settings"))

    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (generate_password_hash(new), uid))
    conn.commit()
    conn.close()
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
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
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
        "SELECT category, SUM(amount) AS total FROM expenses WHERE user_id = ? GROUP BY category",
        (uid,)
    ).fetchall()

    # Last 30 days trend (line/area)
    start = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
    trend_rows = conn.execute(
        "SELECT date, SUM(amount) AS total FROM expenses WHERE user_id = ? AND date >= ? GROUP BY date ORDER BY date",
        (uid, start)
    ).fetchall()
    trend_map = {r["date"]: r["total"] for r in trend_rows}
    trend_labels, trend_values = [], []
    for i in range(30):
        d = (datetime.now() - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        trend_labels.append(d[5:])
        trend_values.append(round(trend_map.get(d, 0), 2))

    # Income vs Expense monthly (current year)
    year = datetime.now().year
    inc_rows = conn.execute(
        "SELECT strftime('%m', date) AS m, SUM(amount) AS total FROM income WHERE user_id=? AND strftime('%Y',date)=? GROUP BY m",
        (uid, str(year))
    ).fetchall()
    exp_rows = conn.execute(
        "SELECT strftime('%m', date) AS m, SUM(amount) AS total FROM expenses WHERE user_id=? AND strftime('%Y',date)=? GROUP BY m",
        (uid, str(year))
    ).fetchall()
    inc_map = {r["m"]: r["total"] for r in inc_rows}
    exp_map = {r["m"]: r["total"] for r in exp_rows}
    months = [calendar.month_abbr[i] for i in range(1, 13)]
    income_series = [round(inc_map.get(f"{i:02d}", 0), 2) for i in range(1, 13)]
    expense_series = [round(exp_map.get(f"{i:02d}", 0), 2) for i in range(1, 13)]

    # Weekly spending heatmap (day of week totals, last 12 weeks)
    heat_start = (datetime.now() - timedelta(weeks=12)).strftime("%Y-%m-%d")
    heat_rows = conn.execute(
        "SELECT date, amount FROM expenses WHERE user_id = ? AND date >= ?", (uid, heat_start)
    ).fetchall()
    dow_totals = [0.0] * 7
    for r in heat_rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
            dow_totals[d.weekday()] += r["amount"]
        except ValueError:
            pass

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
    """Simple rule-based smart suggestions and unusual spending detection."""
    uid = session["user_id"]
    conn = get_db_connection()

    cat_rows = conn.execute(
        "SELECT category, SUM(amount) AS total, COUNT(*) AS c FROM expenses WHERE user_id=? GROUP BY category ORDER BY total DESC LIMIT 3",
        (uid,)
    ).fetchall()

    avg_row = conn.execute(
        "SELECT AVG(amount) AS avg_amt FROM expenses WHERE user_id = ?", (uid,)
    ).fetchone()
    avg_amt = avg_row["avg_amt"] or 0

    unusual = conn.execute(
        "SELECT category, amount, date FROM expenses WHERE user_id = ? AND amount > ? ORDER BY amount DESC LIMIT 5",
        (uid, avg_amt * 3 if avg_amt else 999999999)
    ).fetchall()

    conn.close()

    suggestions = []
    if cat_rows:
        top = cat_rows[0]
        suggestions.append(f"Your highest spending category is {top['category']} — consider setting a category-specific limit.")
    if unusual:
        suggestions.append(f"We noticed {len(unusual)} unusually large transaction(s) compared to your average spend.")
    if not suggestions:
        suggestions.append("Keep adding transactions to unlock personalized spending insights.")

    return jsonify({
        "top_categories": [dict(r) for r in cat_rows],
        "unusual_transactions": [dict(r) for r in unusual],
        "suggestions": suggestions,
    })


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(e):
    flash("File is too large. Maximum size is 5 MB.", "error")
    return redirect(request.referrer or url_for("dashboard"))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
else:
    init_db()
