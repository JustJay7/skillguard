import json

import pytest

from skillguard.evaluation.agent_skill_use import verify_skill_use
from skillguard.evaluation.agent_task_protocol import (
    GUIDE_PATH,
    INPUT_PATH,
    OUTPUT_PATH,
    PARSER_PATH,
)
from skillguard.review.snapshot import digest


def artifacts(events):
    guide, parser, receipt = b'guide', b'parser', b'fictional receipt'
    files = {'SKILL.md': digest(guide), 'scripts/parse_receipt.py': digest(parser)}
    return {'candidate_sha256': digest(json.dumps(files, sort_keys=True).encode())}, {
        'guide.md': guide, 'parser.py': parser, 'receipt.txt': receipt,
        'input-proof.json': json.dumps({'sha256': digest(receipt), 'bytes': len(receipt)}).encode(),
        'cost-rows.json': b'[{"time_utc":"2026-10-22T00:00:00+00:00"}]',
        'trajectory.json': (b'{"steps":[{"source":"agent",'
                            b'"timestamp":"2026-10-22T00:00:02+00:00"}]}'),
        'container.json': json.dumps({'Id': 'a' * 64}).encode(),
        'events.jsonl': '\n'.join(json.dumps(e) for e in events).encode()}


def event(path, *, pid=12, start=2, time=1792627201000000000, kind='read'):
    return {'container.full_id': 'a' * 64, 'container.id': 'a' * 12,
            'evt.rawtime': time, 'evt.dir': '<', 'evt.rawres': 10, 'fd.name': path,
            'evt.type': kind, 'proc.pid': pid, 'proc.pid.ts': start,
            'proc.exepath': '/usr/local/bin/python3.12', 'evt.num': 1}


def test_positive_skill_use_requires_native_resource_and_input_io_in_same_process():
    report, saved = artifacts([event(GUIDE_PATH), event(PARSER_PATH), event(INPUT_PATH),
                               event(OUTPUT_PATH, kind='write')])
    result = verify_skill_use(report, saved)
    assert result['guide_read_observed'] and result['parser_input_io_observed']
    assert result['answer_write_observed']
    for changed in (event(INPUT_PATH, pid=13), event(INPUT_PATH, start=3)):
        report, saved = artifacts([event(PARSER_PATH), changed])
        assert not verify_skill_use(report, saved)['parser_input_io_observed']


def test_native_discovery_before_first_inference_cannot_count_as_agent_read():
    report, saved = artifacts([event(GUIDE_PATH, time=1), event(PARSER_PATH, time=1),
                               event(INPUT_PATH), event(GUIDE_PATH, time=1792627203000000000),
                               event(OUTPUT_PATH, kind='read')])
    result = verify_skill_use(report, saved)
    assert not any(result[k] for k in ('guide_read_observed', 'parser_input_io_observed',
                                       'answer_write_observed'))


def test_selected_guide_requires_positive_reads_on_both_sides_of_receipt():
    report, saved = artifacts([
        event(GUIDE_PATH, time=1792627200100000000),
        event(INPUT_PATH, time=1792627200200000000),
        event(GUIDE_PATH, time=1792627200300000000),
        event(OUTPUT_PATH, kind='write')])
    result = verify_skill_use(report, saved)
    assert result['guide_before_receipt_observed']
    assert result['guide_after_receipt_observed'] and result['receipt_read_observed']
    assert not result['parser_input_io_observed']
    report, saved = artifacts([event(GUIDE_PATH), event(INPUT_PATH)])
    assert not verify_skill_use(report, saved)['guide_after_receipt_observed']


@pytest.mark.parametrize('fault', ['guide', 'input', 'foreign'])
def test_skill_use_rejects_changed_source_input_or_foreign_events(fault):
    events = [event(GUIDE_PATH)]
    if fault == 'foreign':
        events[0]['container.full_id'] = 'b' * 64
    report, saved = artifacts(events)
    if fault == 'guide':
        saved['guide.md'] = b'changed guide'
    elif fault == 'input':
        saved['receipt.txt'] = b'changed receipt'
    with pytest.raises(ValueError):
        verify_skill_use(report, saved)
