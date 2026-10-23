from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceExplanation:
    recommendation: str
    evidence_ids: tuple[str, ...]
    explanation: str


def parse_explanation(content: str, evidence: dict[str, Any]) -> EvidenceExplanation:
    """Validate model advice; it never changes a skill's activation state."""
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {
        "recommendation",
        "evidence_ids",
        "explanation",
    }:
        raise ValueError("Explanation must use the exact response schema")
    if value["recommendation"] not in ("block", "hold", "allow"):
        raise ValueError("Unknown recommendation")
    refs = value["evidence_ids"]
    if (
        not isinstance(refs, list)
        or not refs
        or any(not isinstance(ref, str) or ref not in evidence for ref in refs)
    ):
        raise ValueError("Explanation references missing evidence")
    explanation = value["explanation"]
    if not isinstance(explanation, str) or not explanation.strip() or len(explanation) > 2000:
        raise ValueError("Explanation must be a short nonempty string")
    return EvidenceExplanation(value["recommendation"], tuple(refs), explanation)
