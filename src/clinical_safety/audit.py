"""Append-only, hash-chained audit ledger.

Every evaluation, queue insertion, and reviewer decision is recorded as a
JSON event chained to the previous event's SHA-256 hash. Tampering with any
historical record breaks the chain, which ``verify_chain`` detects. This is
the artifact a startup shows auditors, health-system buyers, and (where
applicable) FDA QMS reviewers: a complete, tamper-evident trail from model
output to human decision.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from .db import write_lock

GENESIS_HASH = "GENESIS"


def _canonical(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def log_event(db: sqlite3.Connection, event_type: str, payload: dict) -> dict:
    # Read-prev-hash + insert must be atomic or concurrent writers fork the chain.
    with write_lock:
        row = db.execute(
            "SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = row["hash"] if row else GENESIS_HASH
        record = {
            "ts": time.time(),
            "event_type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        digest = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
        cur = db.execute(
            """INSERT INTO audit_log (ts, event_type, payload_json, prev_hash, hash)
               VALUES (?, ?, ?, ?, ?)""",
            (record["ts"], event_type, json.dumps(payload, sort_keys=True), prev_hash, digest),
        )
        db.commit()
    return {"seq": cur.lastrowid, "hash": digest, **record}


def verify_chain(db: sqlite3.Connection) -> tuple[bool, int | None]:
    """Return (ok, bad_seq). ``bad_seq`` is None when the chain is intact."""
    rows = db.execute(
        "SELECT seq, ts, event_type, payload_json, prev_hash, hash FROM audit_log ORDER BY seq ASC"
    ).fetchall()
    expected_prev = GENESIS_HASH
    for r in rows:
        record = {
            "ts": r["ts"],
            "event_type": r["event_type"],
            "payload": json.loads(r["payload_json"]),
            "prev_hash": r["prev_hash"],
        }
        if r["prev_hash"] != expected_prev:
            return False, r["seq"]
        if hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest() != r["hash"]:
            return False, r["seq"]
        expected_prev = r["hash"]
    return True, None
