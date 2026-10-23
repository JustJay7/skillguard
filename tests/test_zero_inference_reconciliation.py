import csv
import json

import pytest

from scripts.reconcile_zero_receipt_trial import reconcile
from skillguard.models.bounded_transport import FIELDS
from skillguard.models.probe_claim import claim_probe, proposal_claim_path
from skillguard.review.snapshot import digest


@pytest.mark.parametrize('fault', [
    None, 'request', 'response', 'started_agent', 'wrong_run', 'ledger'])
def test_unused_hold_requires_complete_bound_zero_inference_proof(tmp_path, fault):
    root = tmp_path
    results = root / 'results'
    results.mkdir()
    ledger = results / 'cost_log.csv'
    with ledger.open('w') as output:
        csv.DictWriter(output, fieldnames=FIELDS).writeheader()
    controller = root / 'scripts/native_receipt_controller.py'
    controller.parent.mkdir()
    controller.write_text('Offline unit fixture')
    proposal = results / 'proposal.json'
    proposal.write_text('{}')
    identity = {'run_id': 'fixture', 'maximum_model_requests': 6,
                'proposal_sha256': digest(proposal.read_bytes())}
    claim = proposal_claim_path(results, proposal)
    claim.parent.mkdir(exist_ok=True)
    _, original = claim_probe(ledger, claim, identity)
    claim_bytes = claim.read_bytes()
    folder = results / 'integration/fixture'
    native = folder / 'native-job'
    (native / 'capture').mkdir(parents=True)
    (native / 'cost.csv').write_bytes(original)
    (native / 'controller-result.json').write_text(json.dumps(
        {'mode': 'live', 'error_type': 'ValueError'}))
    (native / 'capture/capture.json').write_text('{"container_full_id":null}')
    report = {'mode': 'live', 'run_id': 'fixture', 'proposal_sha256': digest(proposal.read_bytes()),
              'controller_sha256': digest(controller.read_bytes())}
    if fault == 'request':
        (native / 'requests.json').write_text('[]')
    elif fault == 'response':
        (native / 'responses').mkdir()
        (native / 'responses/response.json').write_text('{}')
    elif fault == 'started_agent':
        (native / 'confinement.json').write_text('{}')
    elif fault == 'wrong_run':
        report['run_id'] = 'other'
    elif fault == 'ledger':
        with (native / 'cost.csv').open('a') as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writerow({'call_id': 'unknown request', 'status': 'reserved'})
    (folder / 'report.json').write_text(json.dumps(report))
    if fault:
        with pytest.raises(ValueError, match='not proved'):
            reconcile(root, folder, proposal)
        assert list(csv.DictReader(ledger.open()))[-1]['reserved_cost_usd'] == '0.6'
    else:
        proof = reconcile(root, folder, proposal)
        assert proof['counted_model_requests'] == 0 and proof['original_claim_remains_consumed']
        assert list(csv.DictReader(ledger.open()))[-1]['status'] == 'native_probe_reconciled'
    assert claim.read_bytes() == claim_bytes
