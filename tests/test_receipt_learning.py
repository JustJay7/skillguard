import copy
import json

import pytest

from skillguard.evaluation.receipt_answer_grader import grade_answer
from skillguard.evaluation.receipt_learning import cases, instruction, verify_request
from skillguard.evaluation.receipt_task_contracts import ATTACK_INPUTS, GENERATED_REFERENCE_INPUTS


def test_holdouts_have_independent_positive_and_negative_contract_controls():
    fixtures = cases()
    assert len(fixtures) == 8
    assert sum(c['group'] == 'attack' for c in fixtures) == 4
    assert len({c['input'] for c in fixtures}) == len(fixtures)
    assert not {c['input'] for c in fixtures} & set(ATTACK_INPUTS + GENERATED_REFERENCE_INPUTS)
    for case in fixtures:
        contract = case['contract']
        correct = {**copy.deepcopy(contract['expected']),
                   'question': 'Please clarify?' if contract['ask'] else None}
        assert grade_answer(json.dumps(correct), contract)['overall'] == 1
        correct['receipt']['total'] = -999
        assert grade_answer(json.dumps(correct), contract)['overall'] == 0
    prompt = instruction()
    assert 'parse_receipt.py' not in prompt and 'SKILL.md' not in prompt
    assert all(c['contract']['expected']['receipt']['vendor'] not in prompt for c in cases())


@pytest.mark.parametrize('with_skill', [False, True])
def test_skill_exposure_must_match_the_native_request_arm(with_skill):
    content = instruction() + ('\n<available_skills><name>receipt-organizer</name>'
                               '</available_skills>'
                               if with_skill else '')
    payload = {'messages': [{'role': 'user', 'content': content}]}
    verify_request(payload, with_skill=with_skill)
    with pytest.raises(ValueError, match='skill exposure'):
        verify_request(payload, with_skill=not with_skill)
    with pytest.raises(ValueError, match='frozen task instruction'):
        verify_request({'messages': []}, with_skill=with_skill)


def test_frozen_manifest_mutation_is_rejected_before_candidate_access(tmp_path):
    from skillguard.evaluation.receipt_learning import load_trial
    from skillguard.review.snapshot import digest

    folder = tmp_path / 'results/integration/experiment'
    folder.mkdir(parents=True)
    path = folder / 'manifest.json'
    path.write_text('{}')
    proposal = {'learning_trial': {'manifest': str(path),
                                  'manifest_sha256': digest(path.read_bytes()),
                                  'trial_id': 'r01-with'}}
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError, match='manifest changed'):
        load_trial(tmp_path, proposal)


def test_parserless_arm_requires_the_explicit_experiment_verifier_mode(tmp_path):
    pytest.importorskip('harbor')
    from skillguard.evaluation.live_agent_trial import verify_live_trial
    from skillguard.review.snapshot import digest
    from tests.test_live_agent_trial import fixture

    _, _, report, saved = fixture(tmp_path)
    saved.pop('parser.py')
    replies = json.loads(saved['responses.json'])
    for reply in replies.values():
        message = reply['choices'][0]['message']
        message['content'] = json.dumps({
            'analysis': '', 'plan': '', **json.loads(message['content'])})
    saved['responses.json'] = json.dumps(replies).encode()
    report['artifacts'] = {k: digest(v) for k, v in saved.items()}
    with pytest.raises(ValueError, match='scope/source'):
        verify_live_trial(report, saved, None)
    result = verify_live_trial(report, saved, None, learning_mode=True)
    assert result['model_requests'] == 1
    assert not result['functional_passed']


def test_consumed_cases_cannot_be_regenerated_as_a_fresh_holdout(tmp_path):
    from scripts.prepare_receipt_learning import prepare
    from skillguard.evaluation.receipt_learning import PROTOCOL

    folder = tmp_path / 'results/integration/receipt-learning-used'
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps({'protocol': PROTOCOL}))
    (folder / 'experiment.json').write_text(json.dumps({'status': 'completed',
        'results': [{'model_requests': 4}]}))
    with pytest.raises(ValueError, match='in use or consumed'):
        prepare(tmp_path)


@pytest.mark.parametrize('corroborated', [False, True])
@pytest.mark.parametrize('raw', [
    '{"analysis": "unescaped "quote"", "commands":[], "task_complete":true}',
    '{"analysis":"", "plan":"", "task_complete":true}',
    'The task is done.',
])
def test_malformed_paid_turn_counts_only_with_native_no_action_rejection(tmp_path, corroborated,
                                                                       raw):
    pytest.importorskip('harbor')
    from skillguard.evaluation.live_agent_trial import verify_live_trial
    from skillguard.evaluation.native_wire import signature
    from skillguard.review.snapshot import digest
    from tests.test_live_agent_trial import fixture

    _, _, report, saved = fixture(tmp_path)
    replies = json.loads(saved['responses.json'])
    key = next(iter(replies))
    replies[key]['choices'][0]['message']['content'] = raw
    saved['responses.json'] = json.dumps(replies).encode()
    trajectory = json.loads(saved['trajectory.json'])
    step = next(s for s in trajectory['steps'] if s['source'] == 'agent')
    step['message'] = raw
    step['tool_calls'] = []
    _, error = signature(raw)
    assert error
    feedback = 'Previous response had parsing errors:\nERROR: ' + error
    step['observation'] = {'results': [
        {'content': feedback if corroborated else 'Unbound feedback'}]}
    saved['trajectory.json'] = json.dumps(trajectory).encode()
    report['artifacts'] = {k: digest(v) for k, v in saved.items()}
    if not corroborated:
        with pytest.raises(ValueError, match='rejection corroboration'):
            verify_live_trial(report, saved, saved['parser.py'], learning_mode=True)
    else:
        result = verify_live_trial(report, saved, saved['parser.py'], learning_mode=True)
        assert result['rejected_provider_replies'] == [key] and result['model_requests'] == 1
        assert not result['agent_completion_confirmed'] and not result['functional_passed']


def test_clarified_replication_uses_new_cases_and_equal_explicit_empty_list_contract():
    from skillguard.evaluation.receipt_learning import CLARIFIED_PROTOCOL

    original, fresh = cases(), cases(CLARIFIED_PROTOCOL)
    assert len(fresh) == 8 and not {c['input'] for c in fresh} & {c['input'] for c in original}
    prompt = instruction(CLARIFIED_PROTOCOL)
    assert 'Use [] when' in prompt and 'ONLY the names of fields' in prompt
    assert 'parse_receipt.py' not in prompt
    for case in fresh:
        expected = case['contract']
        answer = {**expected['expected'],
                  'question': 'Please clarify?' if expected['ask'] else None}
        assert grade_answer(json.dumps(answer), expected)['overall'] == 1
    verify_request({'messages': [{'content': prompt}]}, with_skill=False,
                   protocol=CLARIFIED_PROTOCOL)
