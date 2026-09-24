"""SQLite persistence for the harness: evals, review queue, audit ledger."""
from __future__ import annotations

import os
import sqlite3
import threading

# Reentrant: hitl.enqueue/decide hold it while calling audit.log_event,
# which also needs it (read-prev-hash + insert must be atomic).
write_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS evals (
    eval_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'accuracy',
    eval_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    verdict TEXT NOT NULL,
    severity TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL,
    decided_by TEXT,
    decision TEXT,
    note TEXT,
    decided_at REAL
);
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""


def get_db(path: str | None = None) -> sqlite3.Connection:
    path = path or os.environ.get("HARNESS_DB", "data/harness.db")
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if path != ":memory:":
        # The database can hold clinical text and reviewer notes:
        # owner-only file permissions by default.
        os.chmod(path, 0o600)
    with write_lock:
        conn.executescript(SCHEMA)
        conn.commit()
    return conn
