# Ledger — Expense Tracker

A production-ready personal finance web app built with Flask, SQLite and Chart.js. Track expenses and income, set monthly budgets and savings goals, visualize spending across a dozen chart types, and export reports as CSV, Excel or PDF — all behind a premium, glassmorphism-inspired dashboard with full dark mode support.

## Features

**Authentication**
- Secure signup/login with hashed passwords (Werkzeug)
- Session-based auth, per-user data isolation
- Profile page, change password, delete account

**Expenses**
- Add / edit / delete, with category, amount, description, date, payment mode
- Custom categories with icons, optional receipt upload (image or PDF)
- Live search, category filter, date-range filter, sort by amount/date

**Income**
- Add / edit / delete, with source, amount, description, date
- Live search

**Budget & Goals**
- Monthly budget with live progress bar and over-budget warnings
- Savings goal tracking
- Recurring expenses (weekly / monthly / yearly) with a due-date list

**Dashboard**
- Animated stat cards: total income/expense, balance, budget, savings, transaction counts, average daily spend
- Financial health score, recent transactions, quick actions

**Analytics & Reports**
- Pie/doughnut category breakdown, 30-day trend area chart, income vs. expense bar chart, weekly spending heatmap
- Export CSV, Excel (openpyxl) and formatted PDF (ReportLab), with optional date-range filtering
- Print-friendly report view

**Smart features**
- Rule-based spending insights and unusual-transaction detection (`/api/insights`)
- Upcoming bills from recurring expenses

**Settings**
- Currency & language selection, dark/light mode (persisted per user and in localStorage)
- Tabbed settings UI: General, Appearance, Security, Danger Zone

**UI/UX**
- Custom design system ("The Ledger"): Fraunces display type, Inter body type, IBM Plex Mono for figures
- Glassmorphism topbar, animated count-up stats, skeleton/spinner loading, toast notifications, empty states, responsive sidebar, floating action button, custom 404 page

## Tech Stack

| Layer      | Technology                          |
|------------|--------------------------------------|
| Backend    | Python 3, Flask, Flask sessions       |
| Database   | SQLite (via `sqlite3`)                |
| Data/Export| Pandas, openpyxl, ReportLab           |
| Frontend   | HTML5, CSS3 (custom design system), vanilla JavaScript |
| Charts     | Chart.js                              |
| Icons      | Font Awesome 6                        |

## Folder Structure

```
ExpenseTracker/
├── app.py                  # Flask app: routes, auth, business logic, APIs
├── database.py              # SQLite schema + connection helpers
├── requirements.txt
├── Procfile                 # gunicorn entrypoint for Render/Heroku
├── README.md
├── static/
│   ├── css/style.css        # Full design system (light + dark mode)
│   ├── js/main.js           # Dark mode, search, toasts, sidebar, loaders
│   ├── js/charts.js         # Chart.js rendering from /api/chart-data
│   └── uploads/              # Uploaded receipt files
└── templates/
    ├── base.html            # App shell: sidebar, topbar, toasts
    ├── index.html, login.html, signup.html
    ├── dashboard.html, expenses.html, add_expense.html, edit_expense.html
    ├── income.html, add_income.html, edit_income.html
    ├── budget.html, reports.html, settings.html, profile.html, 404.html
```

## Installation

```bash
# 1. Clone or unzip the project
cd ExpenseTracker

# 2. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app (creates expense_tracker.db automatically on first run)
python app.py
```

Visit `http://localhost:5000` in your browser.

## Environment Variables

| Variable      | Purpose                          | Default (dev only) |
|---------------|-----------------------------------|---------------------|
| `SECRET_KEY`  | Flask session signing key         | insecure dev key    |
| `PORT`        | Port to bind to                   | `5000`               |

Always set a strong, random `SECRET_KEY` in production.

## Deployment (Render)

1. Push this repository to GitHub.
2. On Render, create a new **Web Service** from the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app` (already defined in `Procfile`)
5. Add a `SECRET_KEY` environment variable.
6. Deploy — Render will provision the `PORT` variable automatically.

The included `Procfile` also works out of the box on Heroku.

## Security Notes

- Passwords are hashed with Werkzeug's `generate_password_hash` (PBKDF2).
- All database queries use parameterized statements to prevent SQL injection.
- File uploads are restricted by extension and a 5 MB size cap.
- All expense/income/budget routes are scoped to `session['user_id']`, so users can only ever read or modify their own data.
- For production, run behind HTTPS and set `SESSION_COOKIE_SECURE = True`.

## Future Improvements

- Multi-currency conversion with live exchange rates
- Email-based bill reminders and weekly digest
- OAuth login (Google/GitHub)
- Shared/family budgets with multiple users per ledger
- Native mobile app via the same Flask API

## License

MIT License — free to use, modify and distribute.
