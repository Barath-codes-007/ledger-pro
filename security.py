"""
security.py
Security helpers for Ledger: CSRF tokens, login rate limiting, password
validation and receipt upload validation. Framework-light on purpose so it
can be unit tested without a running app.
"""

import hmac
import os
import re
import secrets
import time
import uuid
from collections import defaultdict, deque

CSRF_SESSION_KEY = "_csrf_token"

MIN_PASSWORD_LENGTH = 8
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60

# Magic-byte signatures for allowed receipt types.
_SIGNATURES = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "pdf": (b"%PDF-",),
}
ALLOWED_RECEIPT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}
RECEIPT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
}


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def get_csrf_token(session) -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def csrf_valid(session, submitted) -> bool:
    expected = session.get(CSRF_SESSION_KEY)
    if not expected or not submitted:
        return False
    return hmac.compare_digest(str(expected), str(submitted))


# ---------------------------------------------------------------------------
# Login rate limiting (in-memory, per process)
# ---------------------------------------------------------------------------
class LoginRateLimiter:
    """Sliding-window limiter on failed logins keyed by (ip, email)."""

    def __init__(self, max_failures=LOGIN_MAX_FAILURES, window=LOGIN_WINDOW_SECONDS):
        self.max_failures = max_failures
        self.window = window
        self._failures = defaultdict(deque)

    def _prune(self, key, now):
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def is_blocked(self, key, now=None) -> bool:
        now = time.time() if now is None else now
        return len(self._prune(key, now)) >= self.max_failures

    def record_failure(self, key, now=None):
        now = time.time() if now is None else now
        self._prune(key, now).append(now)

    def reset(self, key):
        self._failures.pop(key, None)

    def clear(self):
        self._failures.clear()


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def validate_password(password: str):
    """Return an error message, or None if the password is acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain at least one letter and one number."
    return None


# ---------------------------------------------------------------------------
# Receipt uploads
# ---------------------------------------------------------------------------
def receipt_extension(filename: str):
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    return ext if ext in ALLOWED_RECEIPT_EXTENSIONS else None


def content_matches_extension(head: bytes, ext: str) -> bool:
    """Verify the file's leading bytes match its claimed type."""
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return any(head.startswith(sig) for sig in _SIGNATURES.get(ext, ()))


def random_receipt_name(ext: str) -> str:
    return f"{uuid.uuid4().hex}.{ext}"


def save_receipt(file_storage, upload_dir: str):
    """
    Validate and store an uploaded receipt.
    Returns (stored_relative_path, None) on success or (None, error_message).
    The stored name is random; the user-supplied filename is never used.
    """
    ext = receipt_extension(file_storage.filename)
    if not ext:
        return None, "Unsupported receipt type. Use PNG, JPG, GIF, WEBP or PDF."
    head = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if not content_matches_extension(head, ext):
        return None, "The receipt file content does not match its file type."
    os.makedirs(upload_dir, exist_ok=True)
    name = random_receipt_name(ext)
    file_storage.save(os.path.join(upload_dir, name))
    return f"receipts/{name}", None
