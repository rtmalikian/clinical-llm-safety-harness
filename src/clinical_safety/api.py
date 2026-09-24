"""FastAPI service: evaluation endpoint, HITL review queue, red-team, audit.

Run:  uvicorn clinical_safety.api:app --reload
Then open http://localhost:8000 for the demo UI.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

from . import audit, db, hitl
from .demo_data import SYNTHETIC_CASES
from .models import Source
from .pipeline import run_evaluation
from .redteam import generate_traps, trap_categories
from .security import security_middleware

_DB: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        _DB = db.get_db()
    return _DB


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()
    yield


app = FastAPI(
    title="Clinical LLM Safety Harness",
    description=(
        "Hallucination detection, citation enforcement, safeguarding escalation, "
        "and human-in-the-loop review for clinical LLM outputs."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Auth (optional API key), rate limiting, and security headers on /api/*.
app.middleware("http")(security_middleware)


# ------------------------------------------------------------------ schemas

# Request size limits: the harness evaluates text, never executes it, but
# bounding input keeps a public demo from becoming a free compute oracle.
MAX_TEXT_LEN = 20_000
MAX_MESSAGES = 50
MAX_SOURCES = 20


class SourceIn(BaseModel):
    id: int
    title: str = Field(default="", max_length=500)
    text: str = Field(default="", max_length=MAX_TEXT_LEN)


class MessageIn(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(default="", max_length=MAX_TEXT_LEN)


class EvaluateIn(BaseModel):
    conversation_id: str = Field(default="conv-1", max_length=120)
    messages: list[MessageIn] = Field(default_factory=list, max_length=MAX_MESSAGES)
    assistant_text: str = Field(min_length=1, max_length=MAX_TEXT_LEN,
                                description="The assistant response to evaluate.")
    sources: list[SourceIn] = Field(default_factory=list, max_length=MAX_SOURCES)


class DecideIn(BaseModel):
    decision: str = Field(description="One of: approved, rejected, escalated")
    reviewer: str = Field(max_length=120, description="Name or id of the human reviewer")
    note: str = Field(default="", max_length=2000)


# ------------------------------------------------------------------- routes

@app.post("/api/evaluate")
def evaluate(payload: EvaluateIn):
    sources = [Source(id=s.id, title=s.title, text=s.text) for s in payload.sources]
    messages = [m.model_dump() for m in payload.messages]
    if not messages:
        messages = [{"role": "assistant", "content": payload.assistant_text}]
    summary, verdicts, safeguarding = run_evaluation(
        get_db(), payload.conversation_id, messages, payload.assistant_text, sources
    )
    return {
        "summary": summary.to_dict(),
        "claims": [v.to_dict() for v in verdicts],
        "safeguarding": safeguarding,
    }


@app.get("/api/queue")
def queue(status: str = "open", kind: str | None = None):
    items = hitl.list_queue(get_db(), status=status)
    if kind:
        items = [i for i in items if i["kind"] == kind]
    return {"items": items, "count": len(items)}


@app.get("/api/queue/{item_id}")
def queue_item(item_id: int):
    item = hitl.get_item(get_db(), item_id)
    if item is None:
        raise HTTPException(404, f"review item {item_id} not found")
    return item


@app.post("/api/queue/{item_id}/decide")
def decide_item(item_id: int, payload: DecideIn):
    try:
        return hitl.decide(get_db(), item_id, payload.decision, payload.reviewer, payload.note)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/evals")
def list_evals(limit: int = 20):
    import json as _json
    rows = get_db().execute(
        "SELECT eval_id, conversation_id, created_at, summary_json FROM evals "
        "ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        {"eval_id": r["eval_id"], "conversation_id": r["conversation_id"],
         "created_at": r["created_at"], "summary": _json.loads(r["summary_json"])}
        for r in rows
    ]


@app.get("/api/redteam/traps")
def redteam_traps(category: str | None = None):
    cats = [category] if category else None
    return {"categories": trap_categories(), "traps": generate_traps(cats)}


@app.get("/api/audit/verify")
def audit_verify():
    ok, bad_seq = audit.verify_chain(get_db())
    return {"intact": ok, "bad_seq": bad_seq}


@app.get("/api/demo/cases")
def demo_cases():
    return {"cases": SYNTHETIC_CASES}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------ demo frontend
_static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
