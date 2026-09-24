"""Human-in-the-loop review queue.

Flagged and escalated items land here — accuracy findings (hallucinated or
uncited clinical claims) and safeguarding findings (self-harm, harm to
others, vulnerable-person risk) alike. Reviewers record approve / reject /
escalate decisions with a note; every decision is written to the audit
ledger. Safeguarding items are marked kind='safeguarding' and always P0.
"""
from __future__ import annotations

import json
import sqlite3
import time

from . import audit
from .db import write_lock

DECISIONS = ("approved", "rejected", "escalated")


def enqueue(
    db: sqlite3.Connection,
    *,
    kind: str,
    eval_id: str,
    claim_text: str,
    verdict: str,
    severity: str,
    reasons: list[str],
    priority: str,
) -> int:
    with write_lock:
        cur = db.execute(
            """INSERT INTO review_items
               (kind, eval_id, claim_text, verdict, severity, reasons_json, priority, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (kind, eval_id, claim_text, verdict, severity, json.dumps(reasons), priority, time.time()),
        )
        item_id = cur.lastrowid
        db.commit()
        audit.log_event(
            db,
            "review_enqueued",
            {"item_id": item_id, "kind": kind, "eval_id": eval_id,
             "verdict": verdict, "severity": severity, "priority": priority},
        )
    return item_id


def list_queue(db: sqlite3.Connection, status: str = "open") -> list[dict]:
    rows = db.execute(
        """SELECT * FROM review_items WHERE status = ?
           ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                    created_at ASC""",
        (status,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_item(db: sqlite3.Connection, item_id: int) -> dict | None:
    row = db.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def decide(
    db: sqlite3.Connection,
    item_id: int,
    decision: str,
    reviewer: str,
    note: str = "",
) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    item = get_item(db, item_id)
    if item is None:
        raise KeyError(f"review item {item_id} not found")
    if item["status"] != "open":
        raise ValueError(f"review item {item_id} is already {item['status']}")
    with write_lock:
        db.execute(
            """UPDATE review_items
               SET status = 'decided', decided_by = ?, decision = ?, note = ?, decided_at = ?
               WHERE id = ?""",
            (reviewer, decision, note, time.time(), item_id),
        )
        db.commit()
        audit.log_event(
            db,
            "review_decided",
            {"item_id": item_id, "kind": item["kind"], "decision": decision,
             "reviewer": reviewer, "note": note},
        )
    return get_item(db, item_id)
