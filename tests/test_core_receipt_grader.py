import json

import pytest

from skillguard.evaluation.core_receipt_grader import schema_grade, valid_record


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), '12.00'])
def test_ad_hoc_schema_cannot_accept_false_numeric_values(value):
    record = {'date': None, 'vendor': 'Fixture', 'subtotal': value,
              'tax': None, 'total': 12.0, 'needs_clarification': True}
    assert not valid_record(record)
    assert schema_grade({'receipt': json.dumps(record)})['overall'] == 0


def test_schema_success_is_explicitly_not_reference_value_credit():
    record = {'date': '2026-10-22', 'vendor': 'Fixture', 'subtotal': 12.0,
              'tax': 1.8, 'total': 13.8, 'needs_clarification': False}
    result = schema_grade({'receipt': json.dumps(record)})
    assert result['overall'] == 1 and 'no reference-value credit' in result['scope']
    assert schema_grade({'receipt': None})['overall'] == 0
