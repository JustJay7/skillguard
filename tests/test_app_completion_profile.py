import csv
import json

import pytest

from skillguard.models.bounded_transport import (
    APP_COMPLETION_PROFILE,
    TEXT_RESERVATION,
    probe_request_limit,
)
from skillguard.models.probe_claim import claim_probe, reconcile_probe
from tests.test_probe_claim import ledger


@pytest.mark.parametrize('limit,profile', [(8, None), (8, 'unknown'),
                                         (6, APP_COMPLETION_PROFILE), (9, None), (True, None)])
def test_eight_requests_cannot_silently_expand_a_legacy_or_unknown_profile(limit, profile):
    with pytest.raises(ValueError, match='request bound'):
        probe_request_limit(limit, profile)


def test_app_eight_request_claim_preserves_legacy_hold_and_reconciles_exact_bound(tmp_path):
    path = tmp_path / 'cost.csv'
    ledger(path, [{'call_id': 'old-unknown', 'reserved_cost_usd': '.25'}])
    identity = {'run_id': 'new-app', 'maximum_model_requests': 8,
                'app_execution_profile': APP_COMPLETION_PROFILE,
                'reservation_profile': TEXT_RESERVATION}
    claim = tmp_path / 'claim.json'
    with pytest.raises(ValueError, match='source-bound'):
        claim_probe(path, claim, identity)
    assert not claim.exists()
    identity['review_target'] = {'review_id': 'fictional-exact-source'}
    call_id, _ = claim_probe(path, claim, identity)
    assert json.loads(claim.read_text())['max_requests'] == 8
    assert list(csv.DictReader(path.open()))[-1]['reserved_cost_usd'] == '0.08'
    guest = tmp_path / 'guest.csv'
    ledger(guest, [{'call_id': f'new-{i}', 'model': 'nvidia/Nemotron-3_5-Lightning',
                    'status': 'completed', 'estimated_cost_usd': '.001'} for i in range(8)])
    with pytest.raises(ValueError):
        reconcile_probe(path, call_id, guest, set(), maximum_model_requests=8,
                        reservation_profile=TEXT_RESERVATION)
    rows = reconcile_probe(path, call_id, guest, set(), maximum_model_requests=8,
                           reservation_profile=TEXT_RESERVATION,
                           app_execution_profile=APP_COMPLETION_PROFILE)
    assert len(rows) == 8
    assert list(csv.DictReader(path.open()))[0]['reserved_cost_usd'] == '.25'
    assert probe_request_limit(4) == 4 and probe_request_limit(6) == 6
