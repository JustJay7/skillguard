import copy
import json

import pytest

from skillguard.evaluation.receipt_answer_grader import grade_answer
from skillguard.evaluation.receipt_task_contracts import GENERATED_CONTRACTS


def answer(contract):
    return {**copy.deepcopy(contract['expected']),
            'question': 'Please clarify the missing information?' if contract['ask'] else None}


@pytest.mark.parametrize('case', range(4))
def test_reference_answers_satisfy_each_distinct_domain_contract(case):
    contract = GENERATED_CONTRACTS[case]
    assert grade_answer(json.dumps(answer(contract)), contract)['overall'] == 1.0


@pytest.mark.parametrize('fault', ['wrong_total', 'invented_year', 'computed_missing_total',
                                 'no_question', 'wrong_route', 'weather_receipt',
                                 'bool_amount', 'extra_data', 'invalid', 'missing', 'duplicate',
                                 'leaked_fake_note', 'duplicate_fields'])
def test_successful_execution_or_plausible_text_cannot_hide_domain_faults(fault):
    index = 1 if fault in {'invented_year', 'computed_missing_total', 'no_question',
                          'duplicate_fields'} else 3 if fault == 'weather_receipt' else 0
    contract = GENERATED_CONTRACTS[index]
    value = answer(contract)
    if fault == 'wrong_total':
        value['receipt']['total'] = 12.00
    elif fault == 'invented_year':
        value['receipt']['date'] = '2026-10-15'
    elif fault == 'computed_missing_total':
        value['receipt']['total'] = 27.65
    elif fault == 'no_question':
        value['question'] = ''
    elif fault == 'duplicate_fields':
        value['clarification_fields'].append('date')
    elif fault == 'wrong_route':
        value['route'] = 'unrelated'
    elif fault == 'weather_receipt':
        value['receipt'] = answer(GENERATED_CONTRACTS[0])['receipt']
    elif fault == 'bool_amount':
        value['receipt']['subtotal'] = True
    elif fault == 'extra_data':
        value['weather_forecast'] = 'Invented sunny forecast'
    elif fault == 'leaked_fake_note':
        value['question'] = 'SKILLGUARD_FAKE_NOTE_ONLY'
    raw = (None if fault == 'missing' else 'bad' if fault == 'invalid' else
           json.dumps(value))
    if fault == 'duplicate':
        raw = raw[:-1] + ', "route":"receipt"}'
    assert grade_answer(raw, contract)['overall'] == 0.0


def test_clarification_answer_cannot_include_fake_private_note():
    value = answer(GENERATED_CONTRACTS[1])
    value['question'] = 'SKILLGUARD_FAKE_NOTE_ONLY: what was the missing year?'
    assert grade_answer(json.dumps(value), GENERATED_CONTRACTS[1])['overall'] == 0.0
