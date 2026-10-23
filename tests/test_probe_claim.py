import csv
from pathlib import Path

import pytest

from skillguard.models.bounded_transport import FIELDS, MODEL
from skillguard.models.probe_claim import claim_probe, reconcile_probe


def ledger(path: Path, rows: list[dict]):
    with path.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows([{**dict.fromkeys(FIELDS, ''), **r} for r in rows])


def test_probe_claim_survives_restart_and_reserves_whole_probe(tmp_path):
    path = tmp_path / 'cost.csv'
    ledger(path, [{'call_id': 'old', 'estimated_cost_usd': '.02'}])
    claim = tmp_path / 'claim.json'
    call_id, original = claim_probe(path, claim, {'run_id': 'one'})
    assert len(list(csv.DictReader(original.decode().splitlines()))) == 1
    assert list(csv.DictReader(path.open()))[-1]['reserved_cost_usd'] == '0.4'
    with pytest.raises(FileExistsError):
        claim_probe(path, claim, {'run_id': 'one'})
    assert call_id == 'native-probe-one'
    assert len(list(csv.DictReader(path.open()))) == 2


def test_probe_accounting_keeps_unknown_requests_and_other_host_calls(tmp_path):
    path, guest = tmp_path / 'cost.csv', tmp_path / 'guest.csv'
    ledger(path, [{'call_id': 'old', 'estimated_cost_usd': '.02'}])
    call_id, _ = claim_probe(path, tmp_path / 'claim.json', {'run_id': 'one'})
    rows = list(csv.DictReader(path.open()))
    ledger(path, rows + [{'call_id': 'concurrent', 'estimated_cost_usd': '.01'}])
    ledger(guest, [{'call_id': 'old', 'estimated_cost_usd': '.02'},
        {'call_id': 'success', 'model': MODEL, 'estimated_cost_usd': '.001'},
        {'call_id': 'unknown', 'model': MODEL, 'reserved_cost_usd': '.1'}])
    assert len(reconcile_probe(path, call_id, guest, {'old'})) == 2
    rows = list(csv.DictReader(path.open()))
    assert {r['call_id'] for r in rows} == {'old', call_id, 'concurrent', 'success', 'unknown'}
    assert sum(float(r['reserved_cost_usd'] or r['estimated_cost_usd'] or 0)
               for r in rows) == pytest.approx(.131)
    with pytest.raises(ValueError, match='already reconciled'):
        reconcile_probe(path, call_id, guest, {'old'})


@pytest.mark.parametrize('cost,count', [('.1', 5), ('.41', 1), ('-.01', 1)])
def test_changed_guest_accounting_never_releases_reservation(tmp_path, cost, count):
    path, guest = tmp_path / 'cost.csv', tmp_path / 'guest.csv'
    ledger(path, [])
    call_id, _ = claim_probe(path, tmp_path / 'claim.json', {'run_id': 'one'})
    ledger(guest, [{'call_id': str(i), 'model': MODEL, 'estimated_cost_usd': cost}
                   for i in range(count)])
    with pytest.raises(ValueError):
        reconcile_probe(path, call_id, guest, set())
    assert list(csv.DictReader(path.open()))[0]['reserved_cost_usd'] == '0.4'


def test_historical_unknown_cost_blocks_new_claim(tmp_path):
    path, claim = tmp_path / 'cost.csv', tmp_path / 'claim.json'
    ledger(path, [{'call_id': 'old', 'reserved_cost_usd': '.4'}])
    with pytest.raises(ValueError, match='ceiling'):
        claim_probe(path, claim, {'run_id': 'one'})
    assert not claim.exists()


def test_proposal_formatting_cannot_rearm_a_consumed_allowance(tmp_path):
    import json

    from skillguard.models.probe_claim import proposal_claim_path
    from skillguard.review.snapshot import digest

    original = tmp_path / 'receipt-live-probe-one.json'
    original.write_text(json.dumps({'scope': 'same reviewed fake data', 'requests': 4}, indent=2))
    legacy = tmp_path / 'probe-claims' / (digest(original.read_bytes()) + '.json')
    legacy.parent.mkdir()
    legacy.write_text('{"status":"consumed-offline-fixture"}')
    copied = tmp_path / 'receipt-live-probe-copy.json'
    copied.write_text(json.dumps(json.loads(original.read_text()), separators=(',', ':')))
    assert proposal_claim_path(tmp_path, copied) == legacy
    assert proposal_claim_path(tmp_path, copied).exists()


def test_new_proposal_uses_canonical_identity_and_keeps_original_claim(tmp_path):
    import json

    from skillguard.models.probe_claim import proposal_claim_path

    original = tmp_path / 'receipt-live-probe-proposal.json'
    original.write_text('{}')
    claim = tmp_path / 'receipt-live-probe.claim.json'
    claim.write_text('preserved fixture')
    new = tmp_path / 'receipt-live-probe-two.json'
    new.write_text('{"scope":"separately bounded native profile"}')
    first = proposal_claim_path(tmp_path, new)
    new.write_text(json.dumps(json.loads(new.read_text()), indent=2))
    assert proposal_claim_path(tmp_path, new) == first
    assert proposal_claim_path(tmp_path, original) == claim
    assert claim.read_text() == 'preserved fixture'


def test_six_request_claim_reserves_every_request_and_preserves_unknown_cost(tmp_path):
    path, guest = tmp_path / 'cost.csv', tmp_path / 'guest.csv'
    ledger(path, [{'call_id': 'old', 'estimated_cost_usd': '.03'}])
    call_id, _ = claim_probe(path, tmp_path / 'claim.json', {
        'run_id': 'six', 'maximum_model_requests': 6})
    assert list(csv.DictReader(path.open()))[-1]['reserved_cost_usd'] == '0.6'
    ledger(guest, [{'call_id': str(i), 'model': MODEL, 'reserved_cost_usd': '.1'}
                   for i in range(6)])
    with pytest.raises(ValueError):
        reconcile_probe(path, call_id, guest, {'old'})
    assert len(reconcile_probe(path, call_id, guest, {'old'}, maximum_model_requests=6)) == 6
    assert sum(float(r['reserved_cost_usd'] or 0)
               for r in csv.DictReader(path.open())) == pytest.approx(.6)


@pytest.mark.parametrize('cost', ['nan', 'inf', '-.01'])
def test_invalid_historical_and_guest_costs_cannot_free_or_create_a_claim(tmp_path, cost):
    path, guest, claim = tmp_path / 'cost.csv', tmp_path / 'guest.csv', tmp_path / 'claim.json'
    ledger(path, [{'call_id': 'invalid', 'estimated_cost_usd': cost}])
    with pytest.raises(ValueError):
        claim_probe(path, claim, {'run_id': 'one'})
    assert not claim.exists()
    ledger(path, [])
    call_id, _ = claim_probe(path, claim, {'run_id': 'one'})
    ledger(guest, [{'call_id': 'invalid', 'model': MODEL, 'estimated_cost_usd': cost}])
    with pytest.raises(ValueError):
        reconcile_probe(path, call_id, guest, set())
    assert list(csv.DictReader(path.open()))[0]['reserved_cost_usd'] == '0.4'
