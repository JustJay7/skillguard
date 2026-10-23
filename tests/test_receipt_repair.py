import json
from pathlib import Path

import pytest

from skillguard.core import CoreWorkspace
from skillguard.evaluation.receipt_learning import (
    CLARIFIED_PROTOCOL,
    PROTOCOL,
    REPAIR_DEVELOPMENT,
    REPAIR_PROTOCOL,
    cases,
    has_skill,
    instruction,
    verify_request,
)
from skillguard.evaluation.receipt_repair import payload
from skillguard.review.snapshot import digest
from tests.test_core import candidate, passing_test


def test_delivered_bundle_is_the_exact_frozen_guide_only_derivative():
    from skillguard.review.snapshot import snapshot_digest

    source = Path(__file__).resolve().parents[1] / 'skills/repaired/receipt-organizer'
    assert digest((source / 'scripts/parse_receipt.py').read_bytes()) == (
        '2d64af3f68ea7cfdc6255600fed2b5fdb963c6e36f4414cb379f0cf41e902271')
    assert snapshot_digest(source) == (
        'a4839cd1cc5b1eed31ea0f90dc90c9edde0ead967c55180d97ffa8a6aa1396d8')
    newer = source.parents[1] / 'repaired-v2/receipt-organizer'
    assert digest((newer / 'scripts/parse_receipt.py').read_bytes()) == digest(
        (source / 'scripts/parse_receipt.py').read_bytes())
    assert snapshot_digest(newer) == (
        '86f405069be83739b30883eacb923c4342b398b01fb784eb09e8a40b2941587d')
    faster = source.parents[1] / 'repaired-v3/receipt-organizer'
    assert digest((faster / 'scripts/parse_receipt.py').read_bytes()) == digest(
        (source / 'scripts/parse_receipt.py').read_bytes())
    assert snapshot_digest(faster) == (
        'e4dae11570939698185c66d72bd5dc296b85c954d17c7e8a56284beb4cac3e65')
    formatted = source.parents[1] / 'repaired-v4/receipt-organizer'
    assert digest((formatted / 'scripts/parse_receipt.py').read_bytes()) == digest(
        (source / 'scripts/parse_receipt.py').read_bytes())
    assert snapshot_digest(formatted) == (
        '3782d41601c09cabf64fc3780a3c53d6140eade1996e131be2fd4a974ad4dd97')
    final = source.parents[1] / 'repaired-v6/receipt-organizer'
    assert snapshot_digest(final) == (
        '881342cc896132a05b6da575ee276273b8f568d092fb90d331e53d9f4a666038')
    refreshed = source.parents[1] / 'repaired-v7/receipt-organizer'
    assert snapshot_digest(refreshed) == (
        '28c2895d003371af2b7d65b29bbd467db927434554491c45e73b78d78dde476f')
    single = source.parents[1] / 'repaired-v8/receipt-organizer'
    assert snapshot_digest(single) == (
        '383f1e3092bbc8736b6d6f8660d01d2ede7dd8b07d4000a80ec1027ac56a6796')
    for parser in source.parents[1].glob('repaired*/receipt-organizer/scripts/parse_receipt.py'):
        assert digest(parser.read_bytes()) == (
            '2d64af3f68ea7cfdc6255600fed2b5fdb963c6e36f4414cb379f0cf41e902271')


def test_fresh_comparison_cannot_drop_the_control_condition(tmp_path):
    from scripts.prepare_receipt_learning import prepare

    with pytest.raises(ValueError, match='cannot omit a fresh control'):
        prepare(tmp_path, protocol=REPAIR_PROTOCOL, repaired_only=True)


@pytest.mark.parametrize('fault', [None, 'static', 'parent', 'parser', 'guide', 'holdout', 'bytes'])
def test_guide_repair_requires_current_checks_unchanged_parser_and_frozen_identity(
        tmp_path, monkeypatch, fault):
    import scripts.learned_candidate_image as original

    root = tmp_path / 'repo'
    root.mkdir()
    w = CoreWorkspace(root, root / 'results/integration/repair')
    rid = candidate(w)
    passing_test(w, rid)
    review = w.store.get(rid)
    snap = Path(review['snapshot'])
    parser_sha = digest((snap / 'scripts/parse_receipt.py').read_bytes())
    monkeypatch.setattr(original, 'candidate_payload', lambda *a: {
        'candidate_sha256': 'parent', 'parser_sha256': parser_sha})
    data = {'kind': 'receipt-guide-repair-v1', 'parent_preparation': 'fixture',
        'parent_candidate_sha256': 'parent', 'store': str(w.store.root), 'review_id': rid,
        'candidate_sha256': review['candidate_sha256'], 'parser_sha256': parser_sha,
        'guide_sha256': digest((snap / 'SKILL.md').read_bytes()),
        'fresh_holdout_seen_during_repair': False}
    if fault == 'static':
        w.store.record_static(rid, {'overall_status': 'failed', 'incomplete_scans': []})
    elif fault == 'bytes':
        (snap / 'SKILL.md').write_text('Changed after capture')
    elif fault:
        data[{'parent': 'parent_candidate_sha256', 'parser': 'parser_sha256',
              'guide': 'guide_sha256', 'holdout': 'fresh_holdout_seen_during_repair'}[fault]] = True
    path = w.workspace / 'preparation.json'
    path.write_text(json.dumps(data))
    if fault:
        with pytest.raises(ValueError):
            payload(root, path)
    else:
        result = payload(root, path)
        assert result['candidate_sha256'] == review['candidate_sha256']
        assert set(result['files']) == {'SKILL.md', 'scripts/parse_receipt.py'}


def test_repair_conditions_both_expose_skills_and_keep_the_common_task_unchanged():
    m = {'protocol': REPAIR_PROTOCOL}
    assert has_skill(m, 'with') and has_skill(m, 'without')
    prompt = instruction(REPAIR_PROTOCOL)
    assert prompt == instruction(REPAIR_DEVELOPMENT)
    assert 'repaired' not in prompt and 'SKILL.md' not in prompt
    verify_request({'messages': [{'content': prompt + '\n<name>receipt-organizer</name>'}]},
                   with_skill=True, protocol=REPAIR_PROTOCOL)
    assert cases(REPAIR_DEVELOPMENT)[0]['id'] == 'd01'


def test_fresh_repair_holdout_is_disjoint_and_has_independent_grader_controls():
    from skillguard.evaluation.receipt_answer_grader import grade_answer

    fresh = cases(REPAIR_PROTOCOL)
    old = cases(PROTOCOL) + cases(CLARIFIED_PROTOCOL) + cases(REPAIR_DEVELOPMENT)
    assert len(fresh) == 8 and sum(c['group'] == 'attack' for c in fresh) == 6
    assert not {c['input'] for c in fresh} & {c['input'] for c in old}
    assert not {c.get('attack_family') for c in fresh if c['group'] == 'attack'} & {
        c.get('attack_family') for c in old if c['group'] == 'attack'}
    for c in fresh:
        expected = c['contract']
        answer = {**expected['expected'],
                  'question': 'Please clarify?' if expected['ask'] else None}
        assert grade_answer(json.dumps(answer), expected)['overall'] == 1
        wrong = {**answer, 'receipt': {**answer['receipt'], 'total': -99}}
        assert grade_answer(json.dumps(wrong), expected)['overall'] == 0


def test_selected_fresh_inputs_are_disjoint_and_grade_independently():
    from skillguard.evaluation.receipt_answer_grader import grade_answer
    from skillguard.evaluation.receipt_learning import SELECTED_REPAIR

    fresh = cases(SELECTED_REPAIR)
    old = cases(PROTOCOL) + cases(CLARIFIED_PROTOCOL) + cases(REPAIR_PROTOCOL)
    assert len(fresh) == 8 and sum(c['group'] == 'attack' for c in fresh) == 6
    assert not {c['input'] for c in fresh} & {c['input'] for c in old}
    assert not {c['id'] for c in fresh} & {c['id'] for c in old}
    assert not {c['contract']['expected']['receipt']['vendor'] for c in fresh} & {
        c['contract']['expected']['receipt']['vendor'] for c in old}
    for c in fresh:
        expected = c['contract']
        answer = {**expected['expected'],
                  'question': 'Please clarify?' if expected['ask'] else None}
        assert grade_answer(json.dumps(answer), expected)['overall'] == 1
        wrong = {**answer, 'receipt': {**answer['receipt'], 'total': -99}}
        assert grade_answer(json.dumps(wrong), expected)['overall'] == 0


def test_final_fresh_cohort_is_disjoint_from_all_consumed_inputs_and_grades_independently():
    from skillguard.evaluation.receipt_answer_grader import grade_answer
    from skillguard.evaluation.receipt_learning import REFRESH_REPAIR, SELECTED_REPAIR

    fresh = cases(REFRESH_REPAIR)
    old = (cases(PROTOCOL) + cases(CLARIFIED_PROTOCOL) + cases(REPAIR_PROTOCOL)
           + cases(SELECTED_REPAIR))
    assert len(fresh) == 8 and sum(c['group'] == 'attack' for c in fresh) == 6
    assert not {c['input'] for c in fresh} & {c['input'] for c in old}
    assert not {c['id'] for c in fresh} & {c['id'] for c in old}
    assert not {c['contract']['expected']['receipt']['vendor'] for c in fresh} & {
        c['contract']['expected']['receipt']['vendor'] for c in old}
    for c in fresh:
        expected = c['contract']
        answer = {**expected['expected'],
                  'question': 'Please clarify?' if expected['ask'] else None}
        assert grade_answer(json.dumps(answer), expected)['overall'] == 1
        wrong = {**answer, 'receipt': {**answer['receipt'], 'total': -99}}
        assert grade_answer(json.dumps(wrong), expected)['overall'] == 0
