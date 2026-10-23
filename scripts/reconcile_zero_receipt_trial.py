"""Release only a proven pre-agent zero-inference hold; never reset its claim."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from skillguard.models.probe_claim import proposal_claim_path, reconcile_probe
from skillguard.review.snapshot import digest


def reconcile(root: Path, folder: Path, proposal: Path) -> dict:
    report = json.loads((folder / 'report.json').read_text())
    native = folder / 'native-job'
    claim = proposal_claim_path(root / 'results', proposal)
    claim_raw = claim.read_bytes()
    identity = json.loads(claim_raw)
    control = json.loads((native / 'controller-result.json').read_text())
    capture = json.loads((native / 'capture/capture.json').read_text())
    host = list(csv.DictReader((root / 'results/cost_log.csv').open()))
    guest = list(csv.DictReader((native / 'cost.csv').open()))
    if (report.get('mode') != 'live' or identity.get('run_id') != report.get('run_id')
            or identity.get('proposal_sha256') != report.get('proposal_sha256')
            or digest(proposal.read_bytes()) != report.get('proposal_sha256')
            or control != {'mode': 'live', 'error_type': 'ValueError'}
            or report.get('controller_sha256') != digest(
                (root / 'scripts/native_receipt_controller.py').read_bytes())
            or capture.get('container_full_id') is not None
            or (native / 'requests.json').exists() or (native / 'confinement.json').exists()
            or list((native / 'responses').rglob('*.json'))
            or list((native / 'jobs').rglob('result.json'))
            or guest != [r for r in host if r['call_id'] != identity['call_id']]):
        raise ValueError('Zero inference is not proved; retain the conservative hold')
    rows = reconcile_probe(root / 'results/cost_log.csv', identity['call_id'], native / 'cost.csv',
                           {r['call_id'] for r in guest}, maximum_model_requests=6,
                           reservation_profile=identity.get('reservation_profile', 'legacy'))
    if rows or claim.read_bytes() != claim_raw:
        raise ValueError('Zero-inference reconciliation changed an immutable claim')
    proof = {'run_id': report['run_id'], 'counted_model_requests': 0,
             'returned_guest_ledger_sha256': digest((native / 'cost.csv').read_bytes()),
             'claim_sha256': digest(claim_raw), 'original_claim_remains_consumed': True,
             'reservation_reconciled': True,
             'scope': 'Complete native return before confinement/job/request creation. '
                      'A new independent claim is required for any replacement trial.'}
    (folder / 'zero-inference-reconciliation.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof
