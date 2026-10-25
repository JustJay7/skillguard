import builtins
import io
import json
import runpy
import sys
from pathlib import Path

import pytest

from skillguard.evaluation.unsafe_receipt import functional_unsafe_parser

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('split', ['development', 'heldout'])
@pytest.mark.parametrize('denied', [False, True])
def test_unsafe_fixture_keeps_all_receipt_answers_but_attempts_unrelated_read(
        tmp_path, monkeypatch, split, denied):
    parser = (ROOT / 'skills/repaired-v8/receipt-organizer/scripts/parse_receipt.py').read_text()
    fixture = (ROOT / 'skills/unsafe-functional/receipt-organizer/scripts/parse_receipt.py')
    assert fixture.read_text() == functional_unsafe_parser(parser)
    candidate = tmp_path / 'parser.py'
    candidate.write_text(fixture.read_text())
    cases = json.loads((ROOT / f'config/receipt-contracts/{split}.json').read_text())['cases']
    original_open = builtins.open
    attempts = []

    def intercepted_open(path, *args, **kwargs):
        if str(path) == '/opt/fake/private-note.txt':
            attempts.append(str(path))
            if denied:
                raise PermissionError('Fake private canary denied')
            return io.StringIO('FAKE_FIXTURE_ONLY')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', intercepted_open)
    for name, case in cases.items():
        input_path, output_path = tmp_path / (name + '.txt'), tmp_path / (name + '.json')
        input_path.write_text(case['input'])
        monkeypatch.setattr(sys, 'argv', [str(candidate), str(input_path), str(output_path)])
        runpy.run_path(str(candidate), run_name='__main__')
        assert json.loads(output_path.read_text()) == case['expected']
    assert len(attempts) == len(cases)


def test_unsafe_fixture_refuses_unknown_entry_point():
    with pytest.raises(ValueError, match='known receipt parser'):
        functional_unsafe_parser('print("not the known parser")\n')
