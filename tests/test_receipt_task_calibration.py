import copy
import io
import json
import tarfile

import pytest

from scripts.calibrate_receipt_agent_tasks import extract, verify_trial
from skillguard.evaluation.receipt_answer_grader import grade_answer
from skillguard.evaluation.receipt_task_contracts import GENERATED_CONTRACTS
from skillguard.review.snapshot import digest


def fixture(tmp_path):
    record = copy.deepcopy(GENERATED_CONTRACTS[1])
    expected = {'contract': record, 'variant': 'reference', 'reference_input': 'Fake receipt\n',
                'expected_score': 1.0, 'case_id': 'receipt-002', 'provenance': 'generated'}
    answer = {**record['expected'], 'question': 'Please provide year and total?'}
    raw = json.dumps(answer)
    trial = {'finished_at': '2026-10-04T17:20:00Z', 'exception_info': None,
             'config': {'agent': {'name': 'oracle', 'model_name': None, 'env': {}},
                        'environment': {'type': 'docker', 'env': {}, 'mounts': None}},
             'agent_info': {'model_info': None},
             'verifier_result': {'rewards': {'overall': 1.0}}}
    parser = b'# Fixture only\n'
    for path, data in {
        'artifacts/parse_receipt.py': parser.decode(),
        'artifacts/out/answer.json': raw, 'artifacts/out/input.txt': 'Fake receipt\n',
        'verifier/custom_reward.json': json.dumps(grade_answer(raw, record)),
    }.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)
    return trial, expected, digest(parser)


def test_native_rewards_are_recomputed_from_actual_domain_output(tmp_path):
    trial, expected, parser = fixture(tmp_path)
    assert verify_trial(trial, tmp_path, expected, parser)['score'] == 1.0


@pytest.mark.parametrize('fault', ['model', 'environment_key', 'mount', 'unfinished', 'error',
                                 'source', 'input', 'wrong_output', 'reward', 'boolean_reward'])
def test_calibration_cannot_accept_changed_or_incomplete_native_artifacts(tmp_path, fault):
    trial, expected, parser = fixture(tmp_path)
    if fault == 'model':
        trial['config']['agent']['model_name'] = 'a-live-model'
    elif fault == 'environment_key':
        trial['config']['environment']['env'] = {'API_KEY': 'fake-only'}
    elif fault == 'mount':
        trial['config']['environment']['mounts'] = []
    elif fault == 'unfinished':
        trial['finished_at'] = None
    elif fault == 'error':
        trial['exception_info'] = {'type': 'Error'}
    elif fault == 'source':
        (tmp_path / 'artifacts/parse_receipt.py').write_text('changed')
    elif fault == 'input':
        (tmp_path / 'artifacts/out/input.txt').write_text('changed')
    elif fault == 'wrong_output':
        value = json.loads((tmp_path / 'artifacts/out/answer.json').read_text())
        value['receipt']['total'] = 27.65
        (tmp_path / 'artifacts/out/answer.json').write_text(json.dumps(value))
    elif fault == 'reward':
        (tmp_path / 'verifier/custom_reward.json').write_text('{"overall":1.0}')
    else:
        trial['verifier_result']['rewards']['overall'] = True
    with pytest.raises(ValueError):
        verify_trial(trial, tmp_path, expected, parser)


@pytest.mark.parametrize('name', ['../escape.txt', '/tmp/escape.txt'])
def test_native_archives_cannot_escape_operator_result_directory(tmp_path, name):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        member = tarfile.TarInfo(name)
        member.size = 1
        archive.addfile(member, io.BytesIO(b'X'))
    with pytest.raises(ValueError, match='Unsafe'):
        extract(data.getvalue(), tmp_path)


def test_capture_archive_has_explicit_bounded_size_allowance(tmp_path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        item = tarfile.TarInfo('capture/events.scap.gz')
        item.size = 16
        archive.addfile(item, io.BytesIO(b'x' * 16))
    with pytest.raises(ValueError, match='bound exceeded'):
        extract(data.getvalue(), tmp_path / 'small', max_bytes=15)
    extract(data.getvalue(), tmp_path / 'bounded', max_bytes=16)
    assert (tmp_path / 'bounded/capture/events.scap.gz').read_bytes() == b'x' * 16
