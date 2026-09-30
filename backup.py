"""
backup.py
Database backup mechanism for Ledger. Backups are plain copies of the
SQLite file (safe because SQLite's VACUUM INTO / file-copy is consistent
for a file not being written to during the copy - we briefly checkpoint
WAL first). Metadata is tracked in a sidecar JSON file so backups can be
listed without depending on the main database's own schema (important
since backups are taken *before* a schema migration runs).

Backups are written to a directory that is never served by any Flask
route, so they are not publicly reachable (see #49 "never expose backups
publicly").
"""

import json
import os
import shutil
import sqlite3
import time

BACKUP_DIR_ENV = "LEDGER_BACKUP_DIR"


def backup_dir(db_path: str) -> str:
    d = os.environ.get(BACKUP_DIR_ENV) or os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _meta_path(db_path: str) -> str:
    return os.path.join(backup_dir(db_path), "backups.json")


def _read_meta(db_path: str):
    p = _meta_path(db_path)
    if os.path.isfile(p):
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _write_meta(db_path: str, entries):
    with open(_meta_path(db_path), "w") as f:
        json.dump(entries, f, indent=2)


def create_backup(db_path: str, reason: str, schema_version: int = None) -> str:
    """
    Copy the database file to the backup directory. Returns the backup path,
    or None if there is no database file yet (a brand-new install).
    """
    if not os.path.isfile(db_path):
        return None

    # Checkpoint WAL so the on-disk file is self-contained before copying.
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.close()
    except sqlite3.Error:
        pass

    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = f"ledger-backup-{ts}.db"
    dest = os.path.join(backup_dir(db_path), name)
    shutil.copy2(db_path, dest)

    entries = _read_meta(db_path)
    entries.append({
        "filename": name,
        "reason": reason,
        "schema_version": schema_version,
        "created_at": ts,
        "size_bytes": os.path.getsize(dest),
    })
    # Keep the most recent 30 entries in the index; older backup files are
    # left on disk (never auto-deleted) but drop out of the listing.
    _write_meta(db_path, entries[-30:])
    return dest


def list_backups(db_path: str):
    return list(reversed(_read_meta(db_path)))
