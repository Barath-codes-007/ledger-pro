# Ledger — Final QA Checklist

Run against the project brief's own "Final QA Checklist" (#92). Status is
based on the 115-test automated suite (`pytest -q`, all passing as of this
writing) plus direct code reading. Items marked **Not verified** require a
real browser/device or a live Render deployment, neither of which this
environment has — they are not claimed as done.

## Authentication
- [x] Signup works — `tests/test_auth.py`
- [x] Login works — `tests/test_auth.py`
- [x] Logout works (POST-only) — `tests/test_auth.py`
- [x] Password hashing (Werkzeug, 8+ chars, letter+number) — `tests/test_auth.py`, `security.py`
- [x] Session security: HttpOnly/SameSite/Secure cookies, rotation on login, rate limiting — `tests/test_security.py`

## Data isolation
- [x] User A cannot read, edit, delete, refund, reverse, or reconcile User B's data — covered across
      `test_security.py`, `test_accounts_transfers.py`, `test_txn_types.py`, `test_api_v1.py`,
      `test_notifications.py`, `test_import.py`, `test_search_pins_detail.py`, `test_copilot.py`

## Transactions
- [x] Expense CRUD — `tests/test_auth.py`, `test_money.py`
- [x] Income CRUD — `tests/test_income_crud.py` (add/edit/delete + cross-user isolation)
- [x] Transfer (net-worth neutral) — `tests/test_accounts_transfers.py`
- [x] Refund (capped at original amount) — `tests/test_txn_types.py`
- [x] Reversal (preserves history, blocks double-reversal) — `tests/test_txn_types.py`
- [x] Split transaction (parent excluded from totals) — `tests/test_txn_types.py`

## Accounts
- [x] Create — `tests/test_accounts_transfers.py`
- [x] Archive (edit is via re-entry; no in-place balance edit UI beyond transfers/reconciliation by design)
- [x] Balance calculation — `tests/test_accounts_transfers.py`, `test_money.py`

## Accounting
- [x] Debits equal credits on every journal entry — `tests/test_txn_types.py::test_journal_entries_always_balance`

## Budgets
- [x] Calculations correct (uses `amount_minor`, bounded to the month) — `tests/test_notifications.py`

## Goals
- [x] Progress correct, contributions recorded, completion status — `tests/test_analytics.py`,
      `tests/test_calendar_close_snapshot_demo.py`

## Analytics
- [x] Chart-data/insights endpoints aggregate from the same `amount_minor` source as the dashboard — `test_money.py`
- [ ] **Not verified**: pixel-level chart rendering in a real browser (Chart.js itself is unmodified upstream code)

## Reports
- [x] CSV works, includes income and expenses — `tests/test_reports.py`
- [x] Excel works (same data path as CSV, `openpyxl` writer — not independently re-tested beyond route reachability)
- [x] PDF works, includes income/expense/net summary — `tests/test_reports.py`

## Imports
- [x] Validation works (required columns, bad dates/amounts rejected with reasons shown) — `tests/test_import.py`
- [x] Duplicates detected (flagged, skip-by-default, never silently dropped) — `tests/test_import.py`

## Security
- [x] CSRF — token required on every state-changing request — `tests/test_security.py`
- [x] Authorization — every route scoped to `session['user_id']`, tested per-feature as above
- [x] Upload security — magic-byte validation, random filenames, served only to the owner — `tests/test_security.py`
- [x] Rate limiting — login (`test_auth.py`) and API (`test_api_v1.py`)
- [x] Secure sessions — see Authentication above

## Deployment
- [ ] **Not verified**: production startup / Render compatibility. `Procfile`, `Dockerfile`, `.env.example`
      and the CI workflow are in place and `gunicorn app:app` boots locally, but this was never deployed to
      Render itself from this environment. Confirm `SECRET_KEY` is set and that `LEDGER_DB_PATH` /
      `LEDGER_RECEIPT_DIR` point at a persistent disk before relying on it in production.

## UI
- [ ] **Not verified**: desktop / tablet / mobile responsive rendering, and dark/light mode visual
      appearance. The CSS was written with responsive and dark-mode rules throughout (consistent with
      the pre-existing app's approach) and a `prefers-reduced-motion` / `:focus-visible` pass was done
      (#55), but none of this was checked in an actual browser or on a real device from this environment.

## Known limitations, stated plainly (not fixed in this pass)
- The repository layer (`repositories.py`) covers expenses/income/accounts; most of `app.py`'s other
  routes still use inline SQL rather than a repository.
- Accounts are not yet linked from the expense-entry form (`account_id` exists on `expenses` but nothing
  in the UI sets it yet), so "spending by account" will be empty until that's wired up.
- Excel export is exercised only via route reachability in tests, not a byte-level check of the
  generated `.xlsx` file's contents.
- No automated browser/visual testing exists in this project (no Selenium/Playwright); everything above
  is verified at the HTTP/HTML-string level via Flask's test client.
