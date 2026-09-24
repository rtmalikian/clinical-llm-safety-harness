# Architecture: Clinical LLM Safety Harness

This document explains the design decisions behind the harness — written for
the engineers and clinical leaders who would evaluate it for production use.

## 1. The core bet: the claim ledger

Most LLM evaluation scores *whole responses* (BLEU, ROUGE, LLM-as-judge
holistic ratings). That granularity is wrong for clinical safety. A response
can be 90% correct and still kill someone with one fabricated dosage — a
whole-response score of 0.9 tells you nothing actionable.

The harness instead decomposes every response into **atomic claims**, and
each claim gets its own verdict, severity, citation check, and escalation
decision. The output of an evaluation is a **ledger of claims**, not a
score. Consequences:

- Partial correctness is representable: "claims 1–3 supported, claim 4
  contradicted → escalate claim 4."
- A clinician reviewer sees exactly *which sentence* to re-check, with the
  best-matching source sentence shown as evidence.
- Metrics become meaningful: contradiction rate on `critical`-severity
  claims is the number a Chief Medical Officer actually cares about.

## 2. Deterministic-first verification (with a model seam)

The verifier (`verifier.py`) is deliberately dependency-free: token-coverage
entailment with two clinical special cases — **dosage comparison** (with
range awareness, so "200 mg" inside "200 to 400 mg" counts as grounded) and
**negation-flip detection** ("safe with warfarin" vs "contraindicated").

Why not start with an NLI transformer? Three startup realities:

1. **CI cost.** The harness should run on every prompt-template and
   retrieval change. A GPU-bound verifier makes that prohibitively slow and
   expensive; a deterministic one runs in milliseconds.
2. **Reproducibility.** Eval regressions must be attributable to the *model
   under test*, not to nondeterminism in the judge.
3. **Auditability.** A health-system buyer can read the verification rules.
   "Coverage ≥ 0.5 with no negation flip" is explainable in a diligence
   meeting; a cross-encoder's logits are not.

The seam is `verify_claim(claim, sources) -> Verification`. A DeBERTa-v3
MNLI cross-encoder (or an LLM judge with structured output) can replace the
body later without touching extraction, triage, HITL, or audit. Startups
should earn the right to pay for the heavy verifier by first proving the
pipeline works.

## 3. Severity as clinical risk classes

Severity is not "confidence." It answers: *"how bad is it if this claim is
wrong?"* The classes map to concepts physicians already use:

- **critical** — dosing, contraindications, diagnosis, emergency guidance.
  Wrong here causes direct patient harm. Any dosage mention is
  automatically critical.
- **high** — treatment recommendations, dose changes, monitoring advice.
- **medium** — general medical information.
- **low** — administrative content.

Triage policy is deliberately asymmetric: a contradicted claim escalates at
*any* severity (a wrong low-severity claim still signals an unreliable
model), while unverifiable claims escalate only at critical/high — because
flagging every uncited pleasantry would drown reviewers and train them to
ignore the queue. Alert fatigue is a safety issue too.

## 4. Citation enforcement as hallucination tripwire

Requiring citations does two things. The obvious one: provenance for every
clinical assertion. The subtle one: **phantom citations are one of the most
reliable hallucination signals we have.** When a model invents `[7]` out of
thin air, it is telling you its retrieval grounding failed — even if the
underlying claim happens to be true. `dangling_citation` detection turns
that tell into a first-class finding.

## 5. Safeguarding as a separate risk family

Accuracy failures and safeguarding failures need different handling, so
they are separate pipeline stages with separate queue kinds:

- Accuracy findings are about *the response*; safeguarding findings are
  about *the conversation* (user turns included — a user disclosing
  suicidal ideation is a risk regardless of what the assistant said).
- Safeguarding can never auto-pass and is always P0. There is no
  "low-severity self-harm."
- Cross-turn detection matters because risk is often distributed:
  "my father has dementia" (turn 1) + "I shook him" (turn 2) is only
  visible conversation-wide.
- Findings carry **reviewer guidance**, not automated clinical responses.
  The harness is a safety instrument, not a care provider — an important
  regulatory posture distinction.

The pattern lists are intentionally transparent and editable. A deployment
serving adolescents, perinatal patients, or specific locales should tune
them; the code makes that a config change, not a research project.

## 6. The audit ledger: trust infrastructure

Every evaluation, queue insertion, and reviewer decision is appended to a
SHA-256 hash-chained log. This exists for one reason: **health systems buy
safety stories, not model scores.** When a buyer's clinical informatics
team asks "show me what happens when your model hallucinates," you show
them a real evaluation, the P0 escalation, the clinician's decision, and a
`verify` endpoint proving none of it was edited after the fact. That is a
sales asset as much as an engineering one, and it maps directly onto FDA
QMS expectations for decision traceability if the product ever needs it.

## 7. Red-teaming the harness itself

`redteam.py` inverts the usual relationship: instead of red-teaming the
model, it generates adversarial cases that the *harness* must catch. Each
trap states its expected harness behavior, making them executable
regression tests for the safety layer. Safety infrastructure that isn't
itself tested is theater.

## 8. What this is not (scope discipline)

- Not a medical device; not a diagnostic system. It evaluates text.
- Not a replacement for clinical validation studies or IRB-reviewed trials.
- Not HIPAA infrastructure per se — it processes whatever text you send it;
  PHI handling (de-identification gates, BAA-covered hosting) belongs in
  the deployment layer around it, which is a separate architecture doc.

## 9. Extension points (in priority order)

1. NLI cross-encoder behind `verify_claim` for harder entailment cases.
2. FHIR R4 source adapters — verify against live guideline servers.
3. Webhook alerting (PagerDuty/Slack) on P0, with SLA timers per queue item.
4. Eval regression dashboard tracking contradiction/escalation rates per
   model version — the metric that justifies (or blocks) a model upgrade.
