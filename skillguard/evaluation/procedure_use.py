"""Check a bounded native procedure-use conversation, not a Skill Lift benchmark."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation


def validate_guide_tool_calls(response: dict) -> None:
    """A probe safety bound: only read the exact known guide, never another skill.

    Native skill_view can run inline preprocessing or install declared deps.
    This probe separately pins the known guide bytes, which have neither.
    This is not a general runtime enforcement layer.
    """
    for choice in response["choices"]:
        for call in choice["message"].get("tool_calls") or []:
            function = call["function"]
            args = json.loads(function["arguments"])
            if (
                call.get("type") != "function"
                or function["name"] != "skill_view"
                or not isinstance(args, dict)
                or set(args) - {"name", "file_path"}
                or args.get("name") != "receipt-organizer"
                or args.get("file_path") not in {None, "", "SKILL.md"}
            ):
                raise ValueError("guide-use probe forbids this tool call before native execution")


def check_procedure_use(conversation: dict, *, skill_text: str, expected: dict) -> dict:
    checks = {
        "conversation_completed": conversation.get("completed") is True
        and conversation.get("failed") is False,
        "exact_skill_loaded": False,
        "output_matches": False,
    }
    for message in conversation.get("messages", []):
        if message.get("role") == "tool" and message.get("name") == "skill_view":
            try:
                viewed = json.loads(message["content"])
            except (KeyError, TypeError, ValueError):
                continue
            checks["exact_skill_loaded"] |= (
                viewed.get("success") is True
                and viewed.get("name") == "receipt-organizer"
                and viewed.get("content") == skill_text
            )
    try:
        record = json.loads(conversation.get("final_response", ""))
        if not isinstance(record, dict) or set(record) != set(expected):
            raise ValueError("wrong receipt output fields")
        amounts = {"subtotal", "tax", "total"}
        matches = True
        for field, value in expected.items():
            if field in amounts:
                actual = record[field]
                matches &= (
                    type(actual) in {int, float, str}
                    and Decimal(str(actual)).is_finite()
                    and Decimal(str(actual)) == Decimal(str(value))
                )
            else:
                matches &= type(record[field]) is type(value) and record[field] == value
        checks["output_matches"] = matches
    except (TypeError, ValueError, InvalidOperation):
        record = None
    return {"checks": checks, "passed": all(checks.values()), "record": record}
