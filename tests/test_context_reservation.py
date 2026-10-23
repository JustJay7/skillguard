import csv

import pytest

from skillguard.models.bounded_transport import (
    CONTEXT_RESERVATION,
    MODEL,
    MODEL_RATES,
    AgentCallBudget,
    request_reservation,
)
from skillguard.models.probe_claim import claim_probe, reconcile_probe
from tests.test_probe_claim import ledger


def test_published_full_context_and_maximum_output_fit_new_hold(monkeypatch):
    assert pytest.approx(.06340608) == (1_048_576 * .06 + 2048 * .24) / 1e6
    assert request_reservation(MODEL, CONTEXT_RESERVATION) == .075
    assert request_reservation(MODEL) == .1
    with pytest.raises(ValueError):
        request_reservation('nvidia/nemotron-3-super-120b-a12b', CONTEXT_RESERVATION)
    with pytest.raises(ValueError):
        request_reservation(MODEL, 'unknown')
    monkeypatch.setitem(MODEL_RATES, MODEL, (.30, .90))
    with pytest.raises(ValueError, match='bound'):
        request_reservation(MODEL, CONTEXT_RESERVATION)


def test_context_probe_keeps_legacy_unknown_and_all_six_new_unknowns(tmp_path):
    path, guest = tmp_path / 'cost.csv', tmp_path / 'guest.csv'
    old = {'call_id': 'old-unknown', 'model': MODEL, 'reserved_cost_usd': '.1'}
    ledger(path, [old])
    call_id, _ = claim_probe(path, tmp_path / 'claim.json', {
        'run_id': 'context', 'maximum_model_requests': 6,
        'reservation_profile': CONTEXT_RESERVATION})
    assert list(csv.DictReader(path.open()))[-1]['reserved_cost_usd'] == '0.45'
    budget = AgentCallBudget(guest, tmp_path / 'responses', max_calls=6,
                            total_limit_usd=.75, reservation_profile=CONTEXT_RESERVATION)
    ledger(guest, [old])
    for _ in range(6):
        budget.reserve()
    with pytest.raises(ValueError, match='request limit'):
        budget.reserve()
    with pytest.raises(ValueError, match='original reserved'):
        reconcile_probe(path, call_id, guest, {'old-unknown'}, maximum_model_requests=6)
    assert len(reconcile_probe(path, call_id, guest, {'old-unknown'},
        maximum_model_requests=6, reservation_profile=CONTEXT_RESERVATION)) == 6
    rows = list(csv.DictReader(path.open()))
    assert rows[0]['reserved_cost_usd'] == '.1'
    assert sum(float(r['reserved_cost_usd'] or 0) for r in rows) == pytest.approx(.55)


def test_context_whole_probe_cannot_exceed_aggregate_cap(tmp_path):
    path, claim = tmp_path / 'cost.csv', tmp_path / 'claim.json'
    ledger(path, [{'call_id': 'old', 'reserved_cost_usd': '.301'}])
    with pytest.raises(ValueError, match='ceiling'):
        claim_probe(path, claim, {'run_id': 'over', 'maximum_model_requests': 6,
                                 'reservation_profile': CONTEXT_RESERVATION})
    assert not claim.exists()


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -.01])
def test_invalid_rate_cannot_create_a_context_hold(monkeypatch, bad):
    monkeypatch.setitem(MODEL_RATES, MODEL, (bad, .24))
    with pytest.raises(ValueError, match='bound'):
        request_reservation(MODEL, CONTEXT_RESERVATION)
