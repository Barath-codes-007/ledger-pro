# Ledger — Personal Finance Platform

A Flask + SQLite personal finance platform. Default currency is INR (₹), with
support for other currencies. Every amount is stored and summed in integer
minor units (paise), accounts and transfers are backed by a real
double-entry journal, and 117 automated tests cover money math, security,
and cross-user data isolation.

Developed by Barath.

## Features

**Authentication & security** — hashed passwords (8+ chars), CSRF on every
state-changing request, rate-limited logins, session rotation, HttpOnly/
SameSite/Secure cookies, content-validated receipt uploads served only to
their owner, a real Security Center (last login, 2FA/passkeys honestly
labeled "Coming soon"), and per-user data isolation enforced and tested on
every route.

**Money & accounting** — integer-paise money math everywhere (dashboard,
budget, reports, charts, insights) via `money.py`; accounts (bank, cash,
UPI, credit card, loan, etc.) with running balances; transfers that are
verified net-worth-neutral; refunds (capped at the original amount),
reversals (history preserved, double-reversal blocked), splits (one
non-counting parent + N category rows), and signed manual adjustments — all
posted through a genuine double-entry `journal_entries` table where every
posting is checked debit==credit before it's written; account reconciliation
against a stated bank balance; a full audit log.

**Financial statements & analytics** — Income Statement, Balance Sheet, and
Cash Flow Statement built from the same stored transactions as the
dashboard; a 30-day cash flow forecast (always labeled ESTIMATE);
spending-by-merchant and spending-by-account breakdowns; month-over-month
category growth; recurring-payment auto-detection (3+ months of a similar
charge, suggests only); anomaly detection compared against each
transaction's own category history, not a single global average.

**Expenses, income, budget & goals** — categories, custom categories,
receipts, merchant, per-transaction currency (preserved even if the account's
display currency later changes), search/sort/date-range filtering,
duplicate-expense flagging, monthly budget with budget-threshold
notifications, savings goals with contributions and an estimated (never
guaranteed) required monthly saving, and a recurring-expense engine that
actually creates due transactions and advances its own next date.

**Planning tools** — a Financial Calendar (recurring bills, goal target
dates, large expenses for a chosen month); a Month-End Close checklist;
a Financial Snapshot for any month; a CSV/Excel import pipeline (auto-detects
columns, previews valid and invalid rows separately, flags possible
duplicates, nothing is written until confirmed); a Notification Center with
per-user preferences; pinned/favorite accounts and categories; a Recent
Activity feed distinct from the transaction ledger; a full transaction
detail page; smart search ("Food > 1000 September UPI" parses into real
filters); a rule-based Finance Copilot that answers from real calculations
and labels every figure actual or ESTIMATE — never a language model, never
an invented number.

**Platform** — a read-only + CRUD, paginated, rate-limited API v1
(`/api/v1/expenses`, `/income`, `/accounts`, `/net-worth`, `/budgets`,
`/goals`, `/transactions`) with a consistent JSON error shape; a formal
migration framework (`migrations.py`, numbered + idempotent, tracked in
`schema_migrations`); automatic database backups before any migration runs;
a thin repository layer for the busiest tables; Docker + docker-compose;
GitHub Actions CI; a PWA manifest, real icons, and a service worker that
caches static assets only — financial data is never served stale or
offline; demo mode (an isolated, clearly `[DEMO]`-labeled seeded account);
a command palette (Ctrl/Cmd+K) and keyboard shortcuts; an accessibility
pass (skip link, live-region toasts, labeled search, existing
focus-visible/reduced-motion rules confirmed).

**Voice Entry** — a "🎙️ Voice Entry" button on both Add Expense and Add
Income sits above the untouched manual form (never forced). Speech capture
and synthesis use the browser's own Web Speech API — no external service,
no API key. A conversational flow asks one field at a time and skips anything
already said ("I spent 500 rupees on food for lunch at Swiggy by UPI today"
fills category, amount, description, merchant, payment type, currency and
date in one go). For expenses it covers every field the manual form has:
category, amount, description, date, payment type, merchant (optional —
say "skip"), currency (skipped if you said "rupees"/"dollars"), and a
receipt. Saying "no" to "use today's date?" asks for the actual date and
states the accepted formats ("yesterday", "5th October", "two days ago",
"05-10-2026" day-month-year). If an answer can't be understood it says what
went wrong and what to say instead, rather than repeating itself. Answering
"yes" to the receipt question opens Take photo / Upload file / Skip. An
unrecognized category is confirmed before being accepted as a new custom one,
the review card has a server-worded Edit button per field, and a type-your-
answer fallback covers a denied mic or failed recognition. The mic only
opens after the assistant finishes speaking (so it never transcribes its own
voice), and a "Voice on/off" toggle mutes the spoken questions. Save does not
write to the database itself — it fills the real existing form (receipt
included) and submits it through the real existing route, so every manual-
entry protection (CSRF, validation, magic-byte receipt checks, duplicate
detection, audit log, journal posting) applies identically. The understanding
layer (`voice_parser.py`) is deterministic/rule-based, the same honest
pattern as the Finance Copilot — not a call to an external AI model.

**Receipt photos** — Add Expense has a "Take photo" button beside the upload
box: a live camera preview captures a JPEG (downscaled to stay under the
5 MB limit) into the form's real receipt field, with a preview and Remove
button. Needs HTTPS or localhost for the camera; if it's blocked or missing
it falls back to the device's camera app / file picker. Income has no
receipts, so voice income entry doesn't ask for one.

## Explicitly not implemented (by design)

Per the project's own "no fake features" rule:
- Bank sync, live balances, live exchange rates, receipt OCR
- Two-factor authentication / passkeys (UI stub, labeled "Coming soon")
- A general-purpose AI assistant (the Finance Copilot is rule-based by design)
- Full offline financial sync (the service worker explicitly excludes
  financial pages and API routes from its cache)
- Voice entry in any language other than English (architected so another
  language's recognition code and keyword table could be added to
  voice_parser.py later; nothing beyond English is implemented or claimed)
- Voice command shortcuts mid-conversation ("cancel", "change amount" while
  mid-flow) beyond what the field-driven flow and its Edit buttons, Retry,
  and Start Again controls already cover
- Receipt OCR (a photo is stored as the receipt; nothing is read from it)

## Known partial areas (see QA_CHECKLIST.md for the full list)

- The repository layer covers expenses/income/accounts; most of the rest
  of `app.py` still uses inline SQL.
- `account_id` exists on expenses but nothing in the UI sets it yet, so
  "spending by account" will be empty until an account picker is added to
  the expense form.
- No browser/visual testing exists in this project — everything is
  verified at the HTTP/HTML level via Flask's test client. Responsive
  layout and dark/light mode were written consistently with the
  pre-existing app's approach but not visually checked here.

## Tech Stack

| Layer       | Technology                                             |
|-------------|---------------------------------------------------------|
| Backend     | Python 3, Flask                                          |
| Database    | SQLite (via `sqlite3`, WAL mode)                         |
| Data/Export | Pandas, openpyxl, ReportLab                              |
| Frontend    | HTML5, CSS3 (custom design system), vanilla JavaScript   |
| Charts      | Chart.js                                                 |
| Testing     | pytest — 117 tests across money, security, accounting, API, imports, analytics, notifications, search, copilot, PWA, accessibility |

## Folder Structure

```
ExpenseTracker/
├── app.py                  # Routes, auth, business logic, API v1
├── services.py              # Accounts, transfers, journal, statements, forecast,
│                             #   analytics, notifications, calendar, demo mode, search
├── money.py                 # Integer minor-unit money handling (Decimal-based)
├── security.py               # CSRF, login + API rate limiting, password/receipt validation
├── repositories.py           # Thin repository layer (expenses/income/accounts)
├── imports.py                 # CSV/Excel import pipeline
├── copilot.py                 # Rule-based Finance Copilot
├── voice_parser.py             # Rule-based speech-to-structured-data (Voice Entry)
├── migrations.py              # Numbered, idempotent schema migrations
├── backup.py                   # Pre-migration SQLite backups
├── database.py                  # Schema, connection, minor-unit backfill
├── tests/                        # pytest suite (117 tests)
├── QA_CHECKLIST.md                # Final QA sweep against the project brief
├── requirements.txt / requirements-dev.txt
├── Dockerfile / docker-compose.yml
├── .github/workflows/ci.yml       # Install, then test on push/PR
├── .env.example
├── Procfile                        # gunicorn entrypoint for Render/Heroku
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

Visit `http://localhost:5000`. Or try `/demo/start` for a seeded sample account.

### With Docker

```bash
cp .env.example .env          # then set SECRET_KEY
docker compose up --build
```

### Running tests

```bash
pip install -r requirements-dev.txt
npm install --prefix tests/js     # optional: enables the front-end voice-flow tests (jsdom)
pytest -q
```

The front-end tests load the real pages from a live local server and drive the
real `voice-assistant.js` / `receipt-camera.js` with a scripted fake microphone;
they are skipped automatically if Node/jsdom aren't installed.

## Environment Variables

| Variable              | Purpose                                               | Default (dev only)      |
|-----------------------|--------------------------------------------------------|--------------------------|
| `SECRET_KEY`          | Flask session signing key                              | random, regenerated on restart, set this in production |
| `LEDGER_ENV`          | `production` enables Secure cookies (needs HTTPS)      | unset                    |
| `LEDGER_DEBUG`        | `true` allows Flask debug mode outside production      | unset                    |
| `LEDGER_DB_PATH`      | SQLite file path, point at a persistent disk in prod   | `expense_tracker.db`     |
| `LEDGER_RECEIPT_DIR`  | Receipt storage path, point at a persistent disk       | `instance/receipts`      |
| `LEDGER_BACKUP_DIR`   | Where pre-migration backups are written                | `<db dir>/backups`       |
| `PORT`                | Port to bind to                                        | `5000`                   |

## Deployment (Render)

1. Push this repository to GitHub.
2. On Render, create a **Web Service** from the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app` (already in `Procfile`)
5. Set `SECRET_KEY`.
6. **Check whether your Render service has a persistent disk.** If not,
   `LEDGER_DB_PATH`, `LEDGER_RECEIPT_DIR` and `LEDGER_BACKUP_DIR` should
   point at one, or your database, receipts and backups are lost on every
   redeploy.

This was never actually deployed to Render from this environment — see
QA_CHECKLIST.md for exactly what is and isn't verified.

## Security Notes

- Passwords hashed with Werkzeug (`generate_password_hash`)
- All queries parameterized; CSRF tokens on every POST, PUT, PATCH, DELETE
- Receipts validated by content (magic bytes), stored with random names
  outside the public static folder, served only to their owning user
- Login attempts rate-limited per IP + email; API requests rate-limited per user
- Every route touching user data filters by `session['user_id']`, with
  tests asserting user A cannot read, edit, delete, refund, reverse, or
  reconcile user B's data

## License

MIT License — free to use, modify and distribute.
