# Ledger — Personal Finance Platform

A Flask + SQLite personal finance platform. Default currency is INR (₹), with
support for other currencies. Track expenses and income, manage accounts and
transfers, monitor net worth and cash flow, set budgets and savings goals,
and export professional reports — all user-scoped, audited, and backed by
deterministic (no floating-point) money math.

Developed by Barath.

## Features

**Authentication & security**
- Signup/login with hashed passwords (Werkzeug), 8+ character policy
- CSRF protection on every state-changing request, rate-limited logins,
  session rotation on login, HttpOnly/SameSite/Secure cookies
- Receipts stored outside `/static`, random filenames, content-type
  validated, served only to their owner
- Security Center: real last-login time; 2FA and passkeys marked
  "Coming soon" rather than faked
- Per-user data isolation enforced on every query and covered by tests

**Money & accounting**
- All amounts stored in integer minor units (paise) via `Decimal`
  conversion — no floating-point rounding errors (see `money.py`)
- Accounts (bank, cash, UPI, credit card, loan, etc.) with running balances
- Transfers between your own accounts — never counted as income or expense
- Net worth (assets minus liabilities) and monthly cash flow
  (opening + income - expenses = closing), both computed from stored data
- Account reconciliation against a bank statement balance (never
  auto-modifies records)
- Full audit log of transaction, account, goal and security events

**Expenses, income, budget & goals**
- Add/edit/delete with categories, custom categories, receipts, payment
  mode, search, sort and date-range filtering
- Possible-duplicate detection on new expenses (flags, never blocks)
- Monthly budget with live progress and warnings
- Savings goals with contributions, progress and an estimated (never
  guaranteed) required monthly saving
- Recurring expenses that actually generate due transactions and advance
  their own next due date; a dedicated Subscriptions view with monthly/
  yearly cost totals

**Analytics, reports & data quality**
- Dashboard: net worth, cash flow, savings rate, budget usage, category and
  trend charts, weekday spending heatmap
- CSV, Excel and PDF export, covering both income and expenses, filterable
  by date range, type and category; the PDF is a formatted financial report
  with an income/expense/net summary
- Data Quality Center: uncategorized expenses and possible duplicates
- Read-only API v1 (`/api/v1/accounts`, `/api/v1/net-worth`,
  `/api/v1/transactions`), authenticated and user-scoped

**UI/UX**
- Command palette (Ctrl/Cmd+K) and keyboard shortcuts (N/I/A/B/G/R, `/` to
  search)
- Dark/light mode, responsive layout, toasts, empty states, 400/403/404/
  429/500 error pages, `/health` endpoint
- PWA manifest and icons

## Explicitly not implemented (by design)

Per the project's own "no fake features" rule, these are left out rather
than faked. Each would need real infrastructure this project doesn't have:

- Bank sync, live balances, live exchange rates
- Receipt OCR
- An AI Finance Copilot
- Two-factor authentication / passkeys (UI stub only, labeled "Coming soon")
- A full double-entry ledger with per-transaction debit/credit postings
  (accounts and transfers are implemented and balance correctly; a formal
  journal table was not added on top of them)
- Month-end close workflow, financial calendar view

## Tech Stack

| Layer       | Technology                                             |
|-------------|---------------------------------------------------------|
| Backend     | Python 3, Flask                                          |
| Database    | SQLite (via `sqlite3`, WAL mode)                         |
| Data/Export | Pandas, openpyxl, ReportLab                              |
| Frontend    | HTML5, CSS3 (custom design system), vanilla JavaScript   |
| Charts      | Chart.js                                                 |
| Testing     | pytest (40+ tests: auth, isolation, money, accounts, transfers, security, reports) |

## Folder Structure

```
ExpenseTracker/
├── app.py                  # Routes, auth, business logic, API v1
├── services.py              # Accounts, transfers, net worth, cash flow, audit log, recurring engine
├── money.py                 # Integer minor-unit money handling (Decimal-based)
├── security.py               # CSRF, login rate limiting, password & receipt validation
├── database.py               # SQLite schema, migrations, minor-unit backfill
├── tests/                    # pytest suite
├── requirements.txt / requirements-dev.txt
├── Dockerfile / docker-compose.yml
├── .github/workflows/ci.yml  # Install, then test on push/PR
├── .env.example
├── Procfile                  # gunicorn entrypoint for Render/Heroku
└── templates/, static/
```

## Installation

```bash
cd ExpenseTracker
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # then set SECRET_KEY
python app.py
```

Visit `http://localhost:5000`.

### With Docker

```bash
cp .env.example .env          # then set SECRET_KEY
docker compose up --build
```

### Running tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Environment Variables

| Variable              | Purpose                                               | Default (dev only)      |
|-----------------------|--------------------------------------------------------|--------------------------|
| `SECRET_KEY`          | Flask session signing key                              | random, regenerated on restart, set this in production |
| `LEDGER_ENV`          | `production` enables Secure cookies (needs HTTPS)      | unset                    |
| `LEDGER_DEBUG`        | `true` allows Flask debug mode outside production      | unset                    |
| `LEDGER_DB_PATH`      | SQLite file path, point at a persistent disk in prod   | `expense_tracker.db`     |
| `LEDGER_RECEIPT_DIR`  | Receipt storage path, point at a persistent disk       | `instance/receipts`      |
| `PORT`                | Port to bind to                                        | `5000`                   |

## Deployment (Render)

1. Push this repository to GitHub.
2. On Render, create a **Web Service** from the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app` (already in `Procfile`)
5. Set `SECRET_KEY`.
6. **Check whether your Render service has a persistent disk.** If not,
   `LEDGER_DB_PATH` and `LEDGER_RECEIPT_DIR` should point at one, or your
   database and receipts will be lost on every redeploy.

## Security Notes

- Passwords hashed with Werkzeug (`generate_password_hash`)
- All queries parameterized; CSRF tokens on every POST
- Receipts validated by content (magic bytes), stored with random names
  outside the public static folder, served only to their owning user
- Login attempts rate-limited per IP + email
- Every route touching user data filters by `session['user_id']`, with
  tests asserting user A cannot read, edit or delete user B's data

## License

MIT License — free to use, modify and distribute.
