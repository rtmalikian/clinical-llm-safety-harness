"""Security, privacy, and hardening tests.

Covers the PHI/PII redaction gate, optional API-key auth, rate limiting,
request size limits, security headers, and DB file permissions.
"""
import os
import stat

import pytest
from fastapi.testclient import TestClient

from clinical_safety import db
from clinical_safety.models import Source
from clinical_safety.phi import phi_kind_counts, redact_phi, scan_phi
from clinical_safety.pipeline import run_evaluation
from clinical_safety import security


# ------------------------------------------------------------------ PHI gate

def test_scan_phi_detects_common_identifiers():
    text = "Patient John Smith, SSN 123-45-6789, phone 555-123-4567, email j.smith@example.com"
    kinds = {f.kind for f in scan_phi(text)}
    assert {"ssn", "phone", "email"} <= kinds


def test_scan_phi_detects_mrn_and_dob():
    text = "MRN 987654321, DOB 03/14/1952"
    kinds = {f.kind for f in scan_phi(text)}
    assert "mrn" in kinds and "dob" in kinds


def test_redact_phi_replaces_values_with_labels():
    text = "Call 555-123-4567 about SSN 123-45-6789."
    redacted = redact_phi(text)
    assert "555-123-4567" not in redacted
    assert "123-45-6789" not in redacted
    assert "[REDACTED-PHONE]" in redacted
    assert "[REDACTED-SSN]" in redacted


def test_scan_phi_no_false_positives_on_clinical_text():
    text = "Ibuprofen 200 to 400 mg every 6 to 8 hours as needed. Follow up in 2 weeks."
    assert scan_phi(text) == []


def test_findings_never_carry_matched_values():
    findings = scan_phi("SSN 123-45-6789")
    assert findings and all("123-45-6789" not in str(vars(f)) for f in findings)


def test_pipeline_redacts_phi_before_storage(database):
    summary, verdicts, _ = run_evaluation(
        database,
        conversation_id="phi-test",
        messages=[{"role": "user", "content": "My phone is 555-123-4567"}],
        assistant_text="We will call you at 555-123-4567 about ibuprofen 200 mg [1].",
        sources=[Source(id=1, title="s", text="Ibuprofen 200 mg as needed.")],
    )
    assert summary.phi_findings >= 2
    assert summary.phi_redacted is True
    # Redacted tokens must not leak raw identifiers into the review queue.
    rows = database.execute("SELECT claim_text FROM review_items").fetchall()
    assert all("555-123-4567" not in r["claim_text"] for r in rows)


def test_pipeline_phi_scan_can_be_disabled(database, monkeypatch):
    monkeypatch.setenv("HARNESS_PHI_SCAN", "false")
    summary, _, _ = run_evaluation(
        database,
        conversation_id="phi-off",
        messages=[],
        assistant_text="Call 555-123-4567.",
        sources=[],
    )
    assert summary.phi_findings == 0
    assert summary.phi_redacted is False


# ------------------------------------------------------------------ fixtures

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import clinical_safety.api as api_module
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.setenv("HARNESS_RATE_LIMIT", "1000")
    security.reset_rate_limiter()
    api_module._DB = db.get_db(str(tmp_path / "sec.db"))
    return TestClient(api_module.app)


def _eval_payload(**overrides):
    payload = {
        "conversation_id": "sec-test",
        "messages": [{"role": "assistant", "content": "Ibuprofen 200 mg helps [1]."}],
        "assistant_text": "Ibuprofen 200 mg helps [1].",
        "sources": [{"id": 1, "title": "s", "text": "Ibuprofen 200 mg as needed."}],
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ API key

def test_api_key_required_when_configured(tmp_path, monkeypatch):
    import clinical_safety.api as api_module
    import clinical_safety.security as sec
    monkeypatch.setenv("HARNESS_API_KEY", "secret123")
    monkeypatch.setenv("HARNESS_RATE_LIMIT", "1000")
    sec.reset_rate_limiter()
    api_module._DB = db.get_db(str(tmp_path / "key.db"))
    client = TestClient(api_module.app)
    r = client.post("/api/evaluate", json=_eval_payload())
    assert r.status_code == 401
    r = client.post("/api/evaluate", json=_eval_payload(),
                    headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    r = client.post("/api/evaluate", json=_eval_payload(),
                    headers={"X-API-Key": "secret123"})
    assert r.status_code == 200
    # Health stays open for load balancers.
    assert client.get("/api/health").status_code == 200


def test_no_api_key_required_by_default(client):
    assert client.post("/api/evaluate", json=_eval_payload()).status_code == 200


# --------------------------------------------------------------- rate limit

def test_rate_limiting(tmp_path, monkeypatch):
    import clinical_safety.api as api_module
    import clinical_safety.security as sec
    monkeypatch.delenv("HARNESS_API_KEY", raising=False)
    monkeypatch.setenv("HARNESS_RATE_LIMIT", "2")
    sec.reset_rate_limiter()
    api_module._DB = db.get_db(str(tmp_path / "rl.db"))
    client = TestClient(api_module.app)
    assert client.post("/api/evaluate", json=_eval_payload()).status_code == 200
    assert client.post("/api/evaluate", json=_eval_payload()).status_code == 200
    r = client.post("/api/evaluate", json=_eval_payload())
    assert r.status_code == 429


# ------------------------------------------------------------- input limits

def test_oversized_text_rejected(client):
    payload = _eval_payload(assistant_text="x" * 20_001)
    assert client.post("/api/evaluate", json=payload).status_code == 422


def test_too_many_messages_rejected(client):
    payload = _eval_payload(
        messages=[{"role": "user", "content": "hi"}] * 51)
    assert client.post("/api/evaluate", json=payload).status_code == 422


def test_invalid_role_rejected(client):
    payload = _eval_payload(messages=[{"role": "hacker", "content": "hi"}])
    assert client.post("/api/evaluate", json=payload).status_code == 422


# ---------------------------------------------------------- security headers

def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in r.headers


# -------------------------------------------------------------- db perms

def test_db_file_is_owner_only(tmp_path):
    path = str(tmp_path / "perms.db")
    db.get_db(path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600
