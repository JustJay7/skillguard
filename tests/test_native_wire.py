import json

import pytest

pytest.importorskip('harbor')
from skillguard.evaluation.native_wire import rejection_corroborated, signature


def test_native_accepted_fence_and_completion_coercion_preserve_real_commands():
    raw = '```json\n' + json.dumps({'analysis': '', 'plan': '',
        'commands': [{'keystrokes': 'printf fixture\n', 'duration': .5}],
        'task_complete': 'true'}) + '\n```'
    value, error = signature(raw)
    assert not error and value == ([{'keystrokes': 'printf fixture\n', 'duration': .5}], True)


@pytest.mark.parametrize('raw', [
    '{"analysis":"quoted "word"","plan":"","commands":[],"task_complete":true}',
    '{"analysis":"","plan":"","task_complete":true}',
])
def test_native_rejected_turn_never_receives_action_or_completion_credit(raw):
    value, error = signature(raw)
    assert error and value == ([], False)
    step = {'message': raw, 'tool_calls': [], 'observation': {'results': [
        {'content': 'Previous response had parsing errors:\nERROR: ' + error}]}}
    assert rejection_corroborated(raw, error, [step])
    step['tool_calls'] = [{'function_name': 'mark_task_complete', 'arguments': {}}]
    assert not rejection_corroborated(raw, error, [step])
