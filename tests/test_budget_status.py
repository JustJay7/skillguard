import csv

import pytest

from skillguard.models.budget_status import read


def test_current_ledger_keeps_legacy_unknown_and_active_probe_holds(tmp_path):
    path = tmp_path / 'cost.csv'
    with path.open('w') as output:
        writer = csv.DictWriter(output, fieldnames=[
            'status', 'estimated_cost_usd', 'reserved_cost_usd'])
        writer.writeheader()
        writer.writerows([
            {'status': 'completed', 'estimated_cost_usd': '.1154973'},
            {'status': 'failed_unknown', 'reserved_cost_usd': '.1'},
            {'status': 'native_probe_reserved', 'reserved_cost_usd': '.45'}])
    original = path.read_bytes()
    status = read(path)
    assert status['estimated_cost_usd'] == .1154973
    assert status['reserved_usd'] == .55 and status['accounted_usd'] == .6654973
    assert status['completed_requests'] == 1 and path.read_bytes() == original
    assert read(tmp_path / 'missing')['available'] is False


@pytest.mark.parametrize('invalid', ['NaN', 'Infinity', '-1', 'broken'])
def test_budget_view_refuses_invalid_accounting(tmp_path, invalid):
    path = tmp_path / 'cost.csv'
    path.write_text('status,estimated_cost_usd,reserved_cost_usd\ncompleted,' + invalid + ',\n')
    with pytest.raises(ValueError, match='Invalid inference ledger'):
        read(path)
