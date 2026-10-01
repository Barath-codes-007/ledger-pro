"""
imports.py
CSV/Excel import pipeline (#33): Upload -> Validate -> Column Mapping
(auto-detected by common header names) -> Preview -> Duplicate Detection
-> Confirm -> Import. Invalid rows are always shown separately and never
silently discarded; nothing is written to the database until the user
confirms the preview.
"""

import json
import os
import tempfile
import uuid
from datetime import datetime

import pandas as pd

from money import to_minor

# Header names we recognize, case-insensitively, for each logical field.
COLUMN_ALIASES = {
    "date": ["date", "transaction date", "txn date"],
    "amount": ["amount", "value", "debit", "cost"],
    "category": ["category", "type"],
    "description": ["description", "memo", "notes", "narration"],
    "payment_mode": ["payment_mode", "payment method", "mode"],
    "merchant": ["merchant", "payee", "vendor"],
}
REQUIRED_FIELDS = ["date", "amount"]


def _staging_dir():
    d = os.path.join(tempfile.gettempdir(), "ledger_imports")
    os.makedirs(d, exist_ok=True)
    return d


def _detect_columns(columns):
    lower = {c.lower().strip(): c for c in columns}
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower:
                mapping[field] = lower[alias]
                break
    return mapping


def load_dataframe(file_path, filename):
    if filename.lower().endswith(".csv"):
        return pd.read_csv(file_path, dtype=str, keep_default_na=False)
    return pd.read_excel(file_path, dtype=str).fillna("")


def parse_date(value):
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def build_preview(conn, user_id, file_path, filename):
    """
    Returns a dict: {token, columns_found, missing_required, valid_rows,
    invalid_rows}. valid_rows and invalid_rows are lists of dicts; nothing
    is written to the database at this stage. The full valid row set is
    cached to a staging file keyed by token so /import/confirm doesn't
    need the upload again.
    """
    df = load_dataframe(file_path, filename)
    mapping = _detect_columns(df.columns)
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]
    if missing:
        return {"token": None, "columns_found": list(df.columns), "missing_required": missing,
                "valid_rows": [], "invalid_rows": []}

    import services  # local import to avoid a circular import at module load time

    valid_rows, invalid_rows = [], []
    for idx, row in df.iterrows():
        raw_date = row.get(mapping["date"], "")
        raw_amount = row.get(mapping["amount"], "")
        date = parse_date(raw_date)
        try:
            amount_minor = to_minor(raw_amount) if str(raw_amount).strip() else None
        except Exception:
            amount_minor = None

        errors = []
        if not date:
            errors.append(f"unrecognized date '{raw_date}'")
        if amount_minor is None or amount_minor <= 0:
            errors.append(f"invalid amount '{raw_amount}'")

        category = str(row.get(mapping.get("category", ""), "")).strip() or "Other"
        description = str(row.get(mapping.get("description", ""), "")).strip()
        payment_mode = str(row.get(mapping.get("payment_mode", ""), "")).strip() or "Imported"
        merchant = str(row.get(mapping.get("merchant", ""), "")).strip() or None

        if errors:
            invalid_rows.append({"row": idx + 2, "reason": "; ".join(errors), "raw": dict(row.astype(str))})
            continue

        is_dupe = bool(services.find_possible_duplicate(conn, user_id, amount_minor, date, category))
        valid_rows.append({
            "row": idx + 2, "date": date, "category": category, "amount": float(row_to_major(amount_minor)),
            "amount_minor": amount_minor, "description": description, "payment_mode": payment_mode,
            "merchant": merchant, "is_duplicate": is_dupe,
        })

    token = uuid.uuid4().hex
    with open(os.path.join(_staging_dir(), f"{token}.json"), "w") as f:
        json.dump({"user_id": user_id, "filename": filename, "valid_rows": valid_rows}, f)

    return {"token": token, "columns_found": list(df.columns), "missing_required": [],
            "valid_rows": valid_rows, "invalid_rows": invalid_rows}


def row_to_major(amount_minor):
    from money import to_major
    return to_major(amount_minor)


def load_staged(token, user_id):
    path = os.path.join(_staging_dir(), f"{token}.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        data = json.load(f)
    if data.get("user_id") != user_id:
        return None
    return data


def discard_staged(token):
    path = os.path.join(_staging_dir(), f"{token}.json")
    if os.path.isfile(path):
        os.remove(path)


def commit_import(conn, user_id, token, skip_duplicates, currency):
    """Writes the staged valid rows to the expenses table, records an
    import_batches row, and cleans up the staging file. Rows the user
    already saw and chose to skip (duplicates, if skip_duplicates) are
    counted but not inserted - never silently, always reflected in the
    returned counts."""
    from database import now_iso
    import services

    data = load_staged(token, user_id)
    if not data:
        return None

    imported, skipped, duplicate = 0, 0, 0
    for r in data["valid_rows"]:
        if r["is_duplicate"]:
            duplicate += 1
            if skip_duplicates:
                skipped += 1
                continue
        icon = "fa-file-import"
        conn.execute(
            """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description, date,
               payment_mode, currency, merchant, txn_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'expense', ?)""",
            (user_id, r["category"], icon, r["amount"], r["amount_minor"], r["description"], r["date"],
             r["payment_mode"], currency, r["merchant"], now_iso()),
        )
        imported += 1

    cur = conn.execute(
        """INSERT INTO import_batches (user_id, filename, total_rows, imported_rows, skipped_rows,
           duplicate_rows, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, data["filename"], len(data["valid_rows"]), imported, skipped, duplicate, now_iso()),
    )
    services.record_audit(conn, user_id, "import_completed", "import_batch", cur.lastrowid,
                          {"imported": imported, "skipped": skipped, "duplicates": duplicate})
    discard_staged(token)
    return {"imported": imported, "skipped": skipped, "duplicate": duplicate, "batch_id": cur.lastrowid}
