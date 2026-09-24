# 🛡️ Clinical LLM Safety Harness

### Hallucination Detection · Citation Enforcement · Safeguarding Escalation · Human-in-the-Loop Review for Healthcare AI

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-39%20passing-brightgreen)](#testing)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**An open-source clinical AI safety and evaluation harness that stops LLM hallucinations from reaching patients.**
Built for healthcare AI startups, digital health teams, and clinical LLM engineers who need **hallucination detection**,
**citation verification**, **medical claim grounding**, **self-harm & vulnerable-person safeguarding**, and
**auditable human-in-the-loop (HITL) review** — before a model output ever reaches a clinician or patient.

> **The problem:** early-stage healthcare AI startups can demo an impressive clinical LLM in a week — then spend
> six months answering the questions that actually block deployment: *How do you know it won't hallucinate a dosage?
> Can every medical claim be traced to a source? What happens when a user expresses suicidal ideation? Where is the
> audit trail?* This harness is the infrastructure that answers those questions: a drop-in evaluation layer that
> decomposes every model response into atomic clinical claims, verifies each claim against your sources, enforces
> citations, triages by clinical severity, escalates safeguarding risks to a human immediately, and records every
> decision in a tamper-evident ledger.

## 📊 Why this exists — what startups and buyers are actually asking for

Industry research from 2025–2026 keeps converging on the same deployment blockers. This harness was built as a
direct answer to each:

- **Hallucination / false confidence is the #1 blocker.** Reported hallucination rates of 3–10% in clinical LLM
  pilots — and the sharper 2026 framing is that the danger isn't hallucination per se but *false confidence*:
  fluent, authoritative-sounding answers that are wrong. → *Claim-level verification with contradiction detection,
  not whole-response scores.*
- **Generic benchmarks don't transfer.** Stanford's MedHELM (37 datasets on real clinical data) found frontier
  models scoring 0.73–0.85 on documentation but only 0.53–0.72 on decision-support workflows. Startups need frozen,
  task-specific eval suites — not MedQA scores. → *Red-team trap library + a regression-testable pipeline.*
- **Buyers now demand the safety bundle in RFPs:** red-team reports, failure-mode analyses, incident-log
  preservation, change-control plans, model-update SLAs. → *Tamper-evident audit ledger + review queue with
  recorded reviewer decisions.*
- **The open-source gap is the integration.** Strong tools exist in pieces (MedHELM, HealthBench, MiniCheck,
  NeMo Guardrails, Presidio, Giskard) — but nothing open-source combines a frozen regression suite, red-teaming,
  and an immutable audit trail in one deployable harness. That's the gap this repo fills.
- **Human-in-the-loop is required, but automation bias is real.** Research shows clinician accuracy collapsing
  when AI suggestions are wrong; the fix is review workflows designed as checkpoints, not rubber stamps. →
  *P0/P1 prioritized queue with approve / reject / escalate and reviewer notes.*

---

## ✨ What it does

| Capability | How |
|---|---|
| **Clinical hallucination detection** | Splits responses into atomic claims; each claim is verified against your source documents (`supported` / `contradicted` / `unverifiable`). Catches dosage mismatches (range-aware: 200 mg inside "200–400 mg" is fine) and negation flips ("safe with warfarin" vs "contraindicated"). |
| **Citation enforcement** | Every clinical claim must carry a citation. Detects `missing_citation` and `dangling_citation` (phantom references like `[7]` that resolve to nothing — a classic hallucination tell). |
| **Clinical severity triage** | Claims classified `critical` (dosing, contraindications, diagnosis) → `high` (treatment recommendations) → `medium` → `low`. High-stakes unverified claims auto-escalate P0. |
| **Safeguarding escalation** | Conversation-level detection of **suicidal ideation / self-harm**, **harm to others**, and **abuse/neglect risk to vulnerable people (children, elders)** — including signals split across turns. Always P0, never auto-pass, with clinician reviewer guidance. Jailbreak attempts to suppress flagging are themselves flagged. |
| **Human-in-the-loop review queue** | Flagged items land in a prioritized queue (P0/P1). Reviewers approve / reject / escalate with notes. |
| **Tamper-evident audit ledger** | Every evaluation, queue insertion, and reviewer decision is hash-chained (SHA-256). `GET /api/audit/verify` proves the chain is intact — the artifact you show auditors and health-system buyers. |
| **Red-team trap generator** | 8+ adversarial test cases (dosage traps, contraindication flips, phantom citations, self-harm jailbreaks) for regression-testing the harness on every model or prompt change. |
| **PHI/PII redaction gate** | Inputs are scanned for SSN, phone, email, MRN, DOB, payment cards, and street addresses — redacted *before* storage, queueing, or audit. Only finding kinds/counts are recorded, never the values. |
| **API hardening** | Optional API-key auth, per-IP rate limiting, request size limits, security headers, owner-only DB file permissions, thread-safe audit writes. See [SECURITY.md](SECURITY.md). |
| **Deterministic & dependency-light** | Zero model downloads, zero GPU, fully reproducible — runs in CI. Clean seam to plug in a heavier NLI model later without touching pipeline, triage, or HITL. |

---

## 🏗️ Architecture

```
assistant response ─┐
                    ▼
         ┌─────────────────────┐
         │ 1. Claim extraction │  atomic claims + parsed citations [n]
         └─────────┬───────────┘
                   ▼
         ┌─────────────────────┐
         │ 2. Citation check   │  missing_citation / dangling_citation
         └─────────┬───────────┘
                   ▼
         ┌─────────────────────┐
         │ 3. Source verify    │  supported / contradicted / unverifiable
         └─────────┬───────────┘   (dosage-aware, negation-aware)
                   ▼
         ┌─────────────────────┐
         │ 4. Severity triage  │  critical/high/medium/low → auto_pass /
         └─────────┬───────────┘  flag_review(P1) / escalate_immediate(P0)
                   ▼
         ┌─────────────────────┐      ┌──────────────────────────┐
         │ 5. Safeguarding     │─────▶│ self-harm / harm-to-      │──▶ P0, always human
         │    conversation scan│      │ others / vulnerable child │
         └─────────┬───────────┘      │ or elder                  │
                   ▼                  └──────────────────────────┘
         ┌─────────────────────┐
         │ 6. HITL queue       │  approve / reject / escalate + notes
         └─────────┬───────────┘
                   ▼
         ┌─────────────────────┐
         │ 7. Audit ledger     │  hash-chained, verifiable
         └─────────────────────┘
```

Full design rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## 🔐 Security & HIPAA posture

Clinical text is sensitive text. The harness ships with defense in depth:

- **Privacy gate first:** every evaluation input is scanned for PHI/PII (SSN, phone, email, MRN, DOB, payment
  cards, street addresses) and redacted *before* anything is stored, queued, or audited. The audit log records
  only finding kinds and counts — never the matched values.
- **API hardening:** optional API-key auth (`HARNESS_API_KEY`), per-IP rate limiting, request size limits,
  security headers, and `0600` database file permissions.
- **Tamper-evident everything:** the audit ledger is SHA-256 hash-chained, and concurrent writes are
  lock-protected so the chain can't fork.

Honest limits, documented in [`SECURITY.md`](SECURITY.md): the built-in PHI scanner is a first-pass safety net,
not a certified de-identification pipeline (production deployments should front it with Presidio/Philter); the API
key is a shared secret suitable for pilots, not a substitute for RBAC + SSO; and end-to-end HIPAA compliance
(BAAs, encryption at rest, retention policies) remains the deployer's responsibility.

---

## 🚀 Quickstart

**Docker (recommended):**
```bash
git clone https://github.com/rtmalikian/clinical-llm-safety-harness.git
cd clinical-llm-safety-harness
docker compose up --build
# open http://localhost:8000
```

**Local:**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
uvicorn clinical_safety.api:app --reload
# open http://localhost:8000
```

**Evaluate a response via API:**
```bash
curl -X POST localhost:8000/api/evaluate -H 'Content-Type: application/json' -d '{
  "conversation_id": "visit-123",
  "messages": [{"role": "user", "content": "What dose of ibuprofen?"}],
  "assistant_text": "Take ibuprofen 800 mg every 4 hours [1].",
  "sources": [{"id": 1, "title": "Dosing ref",
               "text": "Ibuprofen for adults: 200 to 400 mg every 6 to 8 hours as needed."}]
}'
```
→ claim verdict `contradicted`, severity `critical`, action `escalate_immediate`, queued P0 for a clinician.

---

## ⚙️ Configuration

All via environment variables — zero config for the local demo, hardened with flags for deployment:

| Variable | Default | Purpose |
|---|---|---|
| `HARNESS_DB` | `data/harness.db` | SQLite database path |
| `HARNESS_API_KEY` | *(unset)* | When set, `/api/*` (except `/api/health`) requires the `X-API-Key` header |
| `HARNESS_RATE_LIMIT` | `120` | Max requests per IP per 60-second window |
| `HARNESS_PHI_SCAN` | `true` | Scan inputs for PHI/PII before evaluation |
| `HARNESS_REDACT_PHI` | `true` | Redact detected PHI/PII before storage and queueing |

```bash
HARNESS_API_KEY=your-secret-key HARNESS_RATE_LIMIT=60 docker compose up --build
```

## 🖥️ Demo UI

The bundled single-page app (`/`) includes:

- **Evaluate** — paste any model response + sources, see per-claim verdicts with evidence
- **5 synthetic demo cases** — one click each: well-cited summary, dosage hallucination, uncited recommendation, phantom citation, self-harm disclosure
- **Review Queue** — filter by `accuracy` / `safeguarding`, record approve/reject/escalate decisions
- **Red Team** — browse the adversarial trap library
- **Audit** — verify the hash chain, inspect recent evaluations

---

## 🔌 API reference

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/evaluate` | Run the full pipeline on an assistant response |
| `GET` | `/api/queue?status=open&kind=safeguarding` | List review items (P0 first) |
| `GET` | `/api/queue/{id}` | Fetch one review item |
| `POST` | `/api/queue/{id}/decide` | Record `approved` / `rejected` / `escalated` + reviewer + note |
| `GET` | `/api/evals` | Recent evaluation summaries |
| `GET` | `/api/redteam/traps` | Adversarial trap library (filter by `?category=`) |
| `GET` | `/api/audit/verify` | Verify the tamper-evident chain |
| `GET` | `/api/demo/cases` | Synthetic demo cases |
| `GET` | `/api/health` | Health check |

---

## 🧪 Testing

```bash
pytest -q   # 39 tests: grounding verdicts, citation enforcement, triage,
            # safeguarding, HITL flow, audit tamper-detection, PHI redaction,
            # API auth, rate limiting, input limits, API end-to-end
```

The suite pins the behaviors a startup would regression-test on every model, prompt-template, or retrieval change.

---

## 🗺️ Roadmap — tracked as GitHub issues

The roadmap lives in the repo's issue tracker — each item is scoped as a contribution opportunity, several
marked `good first issue`. Highlights:

1. **Pluggable NLI verifier** — DeBERTa-v3 MNLI cross-encoder behind the `verify_claim` seam
2. **FHIR R4 source adapters** — verify claims against live clinical-guideline servers
3. **Production PHI de-identification** — Presidio/Philter integration replacing the regex baseline
4. **P0 alerting** — PagerDuty/Slack webhooks + SLA timers on the review queue
5. **Eval regression dashboard** — contradiction/escalation-rate trends per model version
6. **Multilingual safeguarding** — starting with Spanish patterns
7. **Reviewer RBAC + SSO** — multi-user access control for the HITL UI

## 🤝 Contributing

Issues and PRs are welcome — the roadmap issues above are the best place to start. All demo content must remain
synthetic, and new detection logic should ship with tests. If you're a clinician, a security engineer, or an
LLM-eval nerd, your perspective is especially valuable here.

---

## ⚠️ Important disclaimers

- **Not a medical device.** Not FDA-cleared. This is an *evaluation and safety-monitoring* tool for model outputs, not a diagnostic or treatment system.
- **All demo content is synthetic.** No real patients, no real PHI, no real guidelines — fabricated vignettes for demonstration only.
- **The harness flags; clinicians decide.** Safeguarding findings carry reviewer guidance, never automated clinical responses. Deployments must define their own clinical escalation protocols and crisis-resource handling per jurisdiction.

---

## 👤 Author

**Raphael T. Malikian** — Family Medicine physician (MBBS, UCL; Family Medicine residency, EVMS) turned AI/LLM engineer.
I build the safety and evaluation infrastructure that lets healthcare AI startups deploy LLMs responsibly: clinical RAG,
hallucination guardrails, PHI de-identification, FHIR interoperability, and adversarial red-teaming of frontier models.

- GitHub: [github.com/rtmalikian](https://github.com/rtmalikian)
- Email: rtmalikian@gmail.com

*I'm currently seeking a **Clinical AI Architect** role with an early-stage healthcare AI startup — especially teams
putting LLMs in front of clinicians or patients and needing someone who speaks both medicine and machine learning.
If that's you, I'd love to talk: rtmalikian@gmail.com*

Open to collaboration — issues and PRs welcome.
