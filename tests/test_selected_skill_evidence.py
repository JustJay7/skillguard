import json

import pytest

from skillguard.evaluation.receipt_learning import (
    SELECTED_DEVELOPMENT,
    SELECTED_REPAIR,
    cases,
    instruction,
)
from skillguard.evaluation.selected_skill_evidence import GUIDE, INPUT, observed


@pytest.mark.parametrize('times,expected', [((3, 4), True), ((4, 3), False), ((1, 4), False)])
def test_only_positive_inference_window_reads_establish_guide_before_input(times, expected):
    rows = [{'fd.name': path, 'evt.type': 'read', 'evt.dir': '<', 'evt.rawres': 1,
             'evt.rawtime': timestamp, 'evt.num': i}
            for i, (path, timestamp) in enumerate(zip((GUIDE, INPUT), times, strict=True))]
    value = observed(('\n'.join(json.dumps(r) for r in rows)).encode(), 2, 5)
    assert value['guide_before_receipt_observed'] is expected


def test_selected_conditions_share_explicit_skill_use_without_a_forced_parser():
    text = instruction(SELECTED_REPAIR)
    assert text == instruction(SELECTED_DEVELOPMENT)
    assert 'SKILL.md before opening the receipt' in text
    assert 'parse_receipt.py' not in text and 'choosing your own extraction tools' in text
    assert [c['id'] for c in cases(SELECTED_DEVELOPMENT)] == ['d01', 'd02']


@pytest.mark.parametrize('refresh_time,expected', [(4, True), (1, False), (6, False)])
def test_refresh_requires_a_positive_guide_read_after_input_inside_agent_window(
        refresh_time, expected):
    rows = [{'fd.name': path, 'evt.type': 'read', 'evt.dir': '<', 'evt.rawres': 1,
             'evt.rawtime': timestamp, 'evt.num': i}
            for i, (path, timestamp) in enumerate(
                [(GUIDE, 2), (INPUT, 3), (GUIDE, refresh_time)])]
    raw = '\n'.join(json.dumps(r) for r in rows).encode()
    assert 'guide_after_receipt_observed' not in observed(raw, 2, 5)
    result = observed(raw, 2, 5, include_refresh=True)
    assert result['guide_before_receipt_observed']
    assert result['guide_after_receipt_observed'] is expected


def test_refresh_revision_keeps_common_task_and_uses_only_known_development_cases():
    from skillguard.evaluation.receipt_learning import REFRESH_DEVELOPMENT, REFRESH_REPAIR

    assert instruction(REFRESH_DEVELOPMENT) == instruction(REFRESH_REPAIR)
    assert instruction(REFRESH_REPAIR) == instruction(SELECTED_REPAIR)
    known = cases(REFRESH_DEVELOPMENT)
    assert [c['id'] for c in known] == ['d01', 'd02', 'd03', 'd04']
    signed = next(c for c in cases(SELECTED_REPAIR) if c['id'] == 'a35')
    assert known[-1]['input'] == signed['input']
