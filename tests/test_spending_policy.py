import json

import pytest

from skillguard.models.bounded_transport import TEXT_RESERVATION
from skillguard.models.budget_status import read
from skillguard.models.probe_claim import claim_probe
from skillguard.models.spending_policy import project_cap, proposal_cap
from tests.test_probe_claim import ledger


def authorize(root, cap):
    (root / 'budget-authorization.json').write_text(json.dumps({
        'aggregate_cap_usd': cap, 'authorization': 'Explicit fictional operator authorization'}))


def test_expanded_operator_budget_keeps_old_claims_and_unknown_holds(tmp_path):
    path = tmp_path / 'cost.csv'
    ledger(path, [{'call_id': 'old-success', 'estimated_cost_usd': '.7'},
                  {'call_id': 'old-unknown', 'reserved_cost_usd': '.25'}])
    original = path.read_bytes()
    assert project_cap(tmp_path) == .75
    authorize(tmp_path, 25.89)
    assert project_cap(tmp_path) == 25.89
    assert proposal_cap(tmp_path) == .75
    with pytest.raises(ValueError, match='ceiling'):
        claim_probe(path, tmp_path / 'legacy-claim.json', {'run_id': 'legacy'})
    assert path.read_bytes() == original
    claim_probe(path, tmp_path / 'new-claim.json', {'run_id': 'new',
        'aggregate_cap_usd': 25.89, 'maximum_model_requests': 6,
        'reservation_profile': TEXT_RESERVATION})
    status = read(path)
    assert status['cap_usd'] == 25.89
    assert status['accounted_usd'] == pytest.approx(1.01)
    assert status['reserved_usd'] == pytest.approx(.31)
    assert path.read_text().splitlines()[1:3] == original.decode().splitlines()[1:3]


@pytest.mark.parametrize('cap', [0, -1, True, 'NaN', 'Infinity', 50.01, 'broken'])
def test_invalid_authorization_fails_closed_instead_of_resetting_accounting(tmp_path, cap):
    authorize(tmp_path, cap)
    with pytest.raises(ValueError):
        project_cap(tmp_path)


def test_proposal_cannot_raise_operator_limit_or_follow_symlink(tmp_path):
    authorize(tmp_path, 1)
    with pytest.raises(ValueError, match='exceeds'):
        proposal_cap(tmp_path, 2)
    path = tmp_path / 'budget-authorization.json'
    path.rename(tmp_path / 'saved.json')
    path.symlink_to(tmp_path / 'saved.json')
    with pytest.raises(ValueError, match='Regular'):
        project_cap(tmp_path)
