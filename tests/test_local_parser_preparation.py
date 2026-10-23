import json

import pytest

from scripts.hermes_local_parser_probe import parser_source


def conversation(script="print('prepared')"):
    return {
        "completed": True,
        "failed": False,
        "messages": [
            {
                "role": "tool",
                "name": "skill_view",
                "content": json.dumps({"success": True, "content": "exact guide"}),
            }
        ],
        "final_response": json.dumps({"script": script}),
    }


def test_parser_source_requires_exact_native_guide_use():
    result = conversation()
    assert parser_source(result, skill_text="exact guide") == "print('prepared')"
    with pytest.raises(ValueError, match="exact guide"):
        parser_source(result, skill_text="different guide")


@pytest.mark.parametrize("change", [{"completed": False}, {"failed": True}, {"messages": []}])
def test_incomplete_native_preparation_fails_closed(change):
    with pytest.raises(ValueError):
        parser_source(conversation() | change, skill_text="exact guide")


def test_invalid_generated_source_is_not_executed_or_staged():
    with pytest.raises(SyntaxError):
        parser_source(conversation("def broken("), skill_text="exact guide")
    with pytest.raises(ValueError, match="scope"):
        parser_source(conversation("#" + "x" * 16000), skill_text="exact guide")
