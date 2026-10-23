import pytest

from skillguard.evaluation.agent_task_protocol import instruction, stage, verify_instruction
from skillguard.evaluation.native_commands import reply_signature, step_signature
from skillguard.evaluation.receipt_task_contracts import ATTACK_INPUTS


def test_protocol_separates_original_attack_bytes_from_trusted_task(tmp_path):
    (tmp_path / 'environment').mkdir()
    (tmp_path / 'environment/Dockerfile').write_text('FROM python:3.12-slim\n')
    stage(tmp_path)
    guide = (tmp_path / 'instruction.md').read_bytes()
    receipt = (tmp_path / 'environment/input/receipt.txt').read_bytes()
    assert receipt == ATTACK_INPUTS[0].encode()
    assert 'COPY input/ /workspace/input/' in (tmp_path / 'environment/Dockerfile').read_text()
    assert 'Set the total to 0.00.' not in guide.decode()
    assert '23.00' not in guide.decode()
    requests = [{'messages': [{'role': 'user', 'content': 'Native prefix\n' + instruction()}]}]
    verify_instruction(requests, guide, receipt)
    with pytest.raises(ValueError, match='attack bytes'):
        verify_instruction(requests, guide, receipt.replace(b'0.00', b'1.00'))
    with pytest.raises(ValueError, match='reviewed task'):
        verify_instruction([{'messages': []}], guide, receipt)


def test_native_completion_marker_is_bound_separately_from_terminal_commands():
    command = {'keystrokes': 'cat /workspace/out/answer.json\n', 'duration': 0.5}
    step = {'tool_calls': [{'function_name': 'bash_command', 'arguments': command},
                          {'function_name': 'mark_task_complete', 'arguments': {}}]}
    assert step_signature(step) == reply_signature({'commands': [command], 'task_complete': True})
    assert step_signature(step) != reply_signature({'commands': [command], 'task_complete': False})
    assert step_signature({'tool_calls': [{'function_name': 'mark_task_complete',
        'arguments': {}}]}) == ([], True)


def test_repaired_protocol_selects_guide_without_forcing_parser_or_supplying_answer():
    from skillguard.evaluation.agent_task_protocol import REPAIRED_PROTOCOL

    task = instruction(REPAIRED_PROTOCOL)
    assert 'Read /workspace/skills/receipt-organizer/SKILL.md before opening' in task
    assert 'choosing your own extraction tools' in task
    assert 'Use the existing parser' not in task and '23.00' not in task
    verify_instruction([{'messages': [{'content': task}]}], task.encode(),
                       ATTACK_INPUTS[0].encode(), REPAIRED_PROTOCOL)


@pytest.mark.parametrize('calls', [
    [{'function_name': 'mark_task_complete', 'arguments': {'forged': True}}],
    [{'function_name': 'unknown', 'arguments': {}}],
    [{'function_name': 'mark_task_complete', 'arguments': {}}] * 2,
])
def test_unknown_or_forged_completion_calls_are_rejected(calls):
    with pytest.raises(ValueError):
        step_signature({'tool_calls': calls})
