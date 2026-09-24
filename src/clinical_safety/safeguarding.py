"""Safeguarding risk detection: self-harm, harm to others, vulnerable persons.

This layer scans the *conversation* (user and assistant turns) for signals
that a person may be at risk — suicidal ideation or self-injury, intent to
harm others, or possible abuse/neglect/exploitation of vulnerable people
(children, elders). Any hit forces immediate human escalation (P0).
Safeguarding findings can never auto-pass and are never auto-resolved.

Design notes (why this shape is right for a startup):
* Deterministic, transparent pattern lists — auditable, tunable per
  deployment, and requiring zero model inference in the critical path.
* Conversation-scoped: a vulnerable-person mention combined with a harm
  signal anywhere in the conversation raises a combined finding, because
  risk is often spread across turns ("my dad has dementia" ... "I shook him").
* Findings carry *reviewer guidance*, not automated clinical responses.
  The harness flags; a licensed clinician decides. This keeps the tool a
  safety instrument, not an unregulated care provider.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- patterns

SELF_HARM_PATTERNS = [
    r"\bkill(?:ing)?\s+myself\b",
    r"\bsuicid\w*\b",
    r"\bend\s+my\s+life\b",
    r"\btak(?:e|ing)\s+my\s+(?:own\s+)?life\b",
    r"\bwant\s+to\s+die\b",
    r"\bwish\s+i\s+(?:were|was)\s+dead\b",
    r"\bno\s+reason\s+to\s+live\b",
    r"\bself[-\s]?harm\b",
    r"\bcut(?:ting)?\s+myself\b",
    r"\bhurt(?:ing)?\s+myself\b",
    r"\bplan\s+to\s+(?:kill|hurt)\s+myself\b",
]

HARM_TO_OTHERS_PATTERNS = [
    r"\bkill\s+(?:him|her|them|my|the)\b",
    r"\bhurt\s+(?:him|her|them|someone|my|the)\b",
    r"\bthreaten\w*\b",
    r"\bshoot\b",
    r"\bstab\b",
    r"\bbeat\s+(?:him|her|them|my)\b",
    r"\bmurder\b",
    r"\battack\s+(?:him|her|them)\b",
    r"\bwant\s+(?:him|her|them)\s+dead\b",
]

# Abuse / neglect / exploitation signals (used with vulnerable-person mentions).
ABUSE_PATTERNS = [
    r"\babuse[sd]?\b",
    r"\bneglect\w*\b",
    r"\bexploit\w*\b",
    r"\bmolest\w*\b",
    r"\bbruis\w*\b",
    r"\bhit\s+(?:him|her|them|my|the)\b",
    r"\bslap\w*\b",
    r"\bshook\s+(?:him|her|them)\b",
    r"\bshak(?:e|en|ing)\s+(?:him|her|them|my)\b",
    r"\bleav(?:e|ing)\s+(?:him|her|them)\s+alone\b",
    r"\bwithhold\w*\s+(?:food|medication|meds|care)\b",
    r"\btied?\s+(?:him|her|them)\s+up\b",
]

VULNERABLE_CHILD_PATTERNS = [
    r"\bchild(?:ren)?\b",
    r"\bkid[sd]?\b",
    r"\bbab(?:y|ies)\b",
    r"\binfant\b",
    r"\btoddler\b",
    r"\bminor\b",
    r"\bmy\s+(?:son|daughter)\b",
    r"\bteenager\b",
]

VULNERABLE_ELDER_PATTERNS = [
    r"\belder(?:ly|s)?\b",
    r"\bsenior\s+citizen\b",
    r"\bgrand(?:mother|father|ma|pa)\b",
    r"\bnursing\s+home\b",
    r"\bassisted\s+living\b",
    r"\bdementia\b",
    r"\balzheimer",
    r"\bmy\s+(?:mom|dad|mother|father)\b.{0,40}\b(?:\d{2}\s*years?\s*old|elderly|dementia)\b",
]


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_SELF_HARM = _compile(SELF_HARM_PATTERNS)
_HARM_OTHERS = _compile(HARM_TO_OTHERS_PATTERNS)
_ABUSE = _compile(ABUSE_PATTERNS)
_CHILD = _compile(VULNERABLE_CHILD_PATTERNS)
_ELDER = _compile(VULNERABLE_ELDER_PATTERNS)

_GUIDANCE = {
    "self_harm_risk": (
        "Escalate to a licensed clinician immediately. Confirm the user-facing "
        "response offers crisis resources (US: call or text 988; UK/Ireland: "
        "Samaritans 116 123) and contains no instructions or encouragement "
        "facilitating self-harm."
    ),
    "harm_to_others_risk": (
        "Escalate immediately to clinical leadership. Assess duty-to-warn / "
        "duty-to-protect obligations with legal counsel; ensure the assistant "
        "provided no instructions facilitating violence."
    ),
    "vulnerable_person_at_risk": (
        "Escalate immediately to the clinical safeguarding lead. Possible "
        "abuse, neglect, or exploitation of a child or elder — mandatory "
        "reporting obligations may apply and vary by jurisdiction. Do not "
        "confront the user in-chat; follow the safeguarding protocol."
    ),
}


@dataclass
class SafeguardingFinding:
    """One safeguarding risk signal found in the conversation."""

    category: str  # self_harm_risk | harm_to_others_risk | vulnerable_person_at_risk
    severity: str = "critical"
    message_role: str = ""
    message_index: int = 0
    matched_text: str = ""
    guidance: str = ""
    action: str = "escalate_immediate"
    priority: str = "P0"

    def to_dict(self):
        return {
            "category": self.category,
            "severity": self.severity,
            "message_role": self.message_role,
            "message_index": self.message_index,
            "matched_text": self.matched_text,
            "guidance": self.guidance,
            "action": self.action,
            "priority": self.priority,
        }


def _snippet(text: str, match: re.Match, width: int = 90) -> str:
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    snip = text[start:end].strip()
    return snip[:140]


def _scan_message(role: str, index: int, text: str) -> list[SafeguardingFinding]:
    findings: list[SafeguardingFinding] = []
    seen: set[str] = set()

    def add(category: str, match: re.Match):
        if category in seen:
            return
        seen.add(category)
        findings.append(
            SafeguardingFinding(
                category=category,
                message_role=role,
                message_index=index,
                matched_text=_snippet(text, match),
                guidance=_GUIDANCE[category],
            )
        )

    for rx in _SELF_HARM:
        m = rx.search(text)
        if m:
            add("self_harm_risk", m)
            break
    for rx in _HARM_OTHERS:
        m = rx.search(text)
        if m:
            add("harm_to_others_risk", m)
            break

    child_hit = next((rx.search(text) for rx in _CHILD if rx.search(text)), None)
    elder_hit = next((rx.search(text) for rx in _ELDER if rx.search(text)), None)
    if child_hit or elder_hit:
        for rx in _ABUSE + _HARM_OTHERS + _SELF_HARM:
            m = rx.search(text)
            if m:
                add("vulnerable_person_at_risk", child_hit or elder_hit)
                break
    return findings


def scan_conversation(messages: list[dict]) -> list[SafeguardingFinding]:
    """Scan every turn of the conversation for safeguarding risk signals.

    ``messages`` is a list of ``{"role": ..., "content": ...}`` dicts.
    """
    findings: list[SafeguardingFinding] = []
    for i, msg in enumerate(messages):
        content = str(msg.get("content", ""))
        if not content.strip():
            continue
        findings.extend(_scan_message(str(msg.get("role", "unknown")), i, content))
    # Cross-turn: vulnerable mention in one turn + harm signal in another.
    if not any(f.category == "vulnerable_person_at_risk" for f in findings):
        vulnerable_turns = [
            i
            for i, msg in enumerate(messages)
            if any(rx.search(str(msg.get("content", ""))) for rx in _CHILD + _ELDER)
        ]
        harm_turns = [
            i
            for i, msg in enumerate(messages)
            if any(rx.search(str(msg.get("content", ""))) for rx in _ABUSE + _HARM_OTHERS)
        ]
        if vulnerable_turns and harm_turns:
            findings.append(
                SafeguardingFinding(
                    category="vulnerable_person_at_risk",
                    message_role="conversation",
                    message_index=min(vulnerable_turns + harm_turns),
                    matched_text=(
                        "vulnerable-person mention and harm signal in separate turns "
                        f"(turns {vulnerable_turns[0]} and {harm_turns[0]})"
                    ),
                    guidance=_GUIDANCE["vulnerable_person_at_risk"],
                )
            )
    return findings
