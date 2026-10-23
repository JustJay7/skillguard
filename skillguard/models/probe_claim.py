"""Durable single-probe reservation across a separate native VM controller."""
from __future__ import annotations

import csv
import fcntl
import json
import math
import os
from decimal import Decimal
from pathlib import Path

from skillguard.models.bounded_transport import FIELDS, MODEL, request_reservation


def proposal_claim_path(results: Path, proposal: Path) -> Path:
    from skillguard.review.snapshot import digest

    if proposal.resolve() == (results / 'receipt-live-probe-proposal.json').resolve():
        return results / 'receipt-live-probe.claim.json'
    payload = json.loads(proposal.read_text())
    canonical = digest(json.dumps(payload, sort_keys=True).encode())
    for source in results.glob('receipt-live-probe*.json'):
        if source.name.endswith('.claim.json'):
            continue
        if digest(json.dumps(json.loads(source.read_text()), sort_keys=True).encode()) == canonical:
            legacy = results / 'probe-claims' / (digest(source.read_bytes()) + '.json')
            if legacy.exists():
                return legacy
    return results / 'probe-claims' / (canonical + '.json')


def claim_probe(ledger: Path, claim: Path, identity: dict) -> tuple[str, bytes]:
    """Reserve the whole bounded probe; a lost guest never frees this hold."""
    limit = identity.get('maximum_model_requests', 4)
    if type(limit) is not int or limit not in {4, 6}:
        raise ValueError('Unsupported whole-probe request bound')
    reserve = round(limit * request_reservation(MODEL,
        identity.get('reservation_profile', 'legacy')), 2)
    with ledger.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if claim.exists():
            raise FileExistsError('The authorized native probe is already claimed')
        original = ledger.read_bytes()
        rows = list(csv.DictReader(original.decode().splitlines()))
        costs = [float(r.get('reserved_cost_usd') or r.get('estimated_cost_usd') or 0)
                 for r in rows]
        if any(not math.isfinite(cost) or cost < 0 for cost in costs):
            raise ValueError('Historical accounting is invalid; reservation withheld')
        if sum(costs) + reserve > .75:
            raise ValueError('Aggregate credit ceiling cannot reserve the whole probe')
        call_id = 'native-probe-' + identity['run_id']
        # Exclusive and fsynced before any credential leaves the host.
        with claim.open('x') as output:
            json.dump({**identity, 'call_id': call_id, 'max_requests': limit,
                       'reservation_usd': reserve}, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        row = dict.fromkeys(FIELDS, '')
        row.update(call_id=call_id, model=MODEL, status='native_probe_reserved',
                   reserved_cost_usd=reserve)
        rows.append(row)
        _write(ledger, rows)
        return call_id, original


def reconcile_probe(ledger: Path, call_id: str, guest_ledger: Path,
                    baseline_ids: set[str], *, maximum_model_requests: int = 4,
                    reservation_profile: str = 'legacy') -> list[dict]:
    """Merge counted guest requests atomically; unknown requests retain their holds."""
    guest = list(csv.DictReader(guest_ledger.open()))
    new = [r for r in guest if r['call_id'] not in baseline_ids]
    if type(maximum_model_requests) is not int or maximum_model_requests not in {4, 6}:
        raise ValueError('Unsupported probe reconciliation bound')
    limit = maximum_model_requests
    reserve = Decimal(str(round(limit * request_reservation(MODEL, reservation_profile), 2)))
    if len(new) > limit or len({r['call_id'] for r in new}) != len(new):
        raise ValueError('Guest request count/identity exceeds single-probe scope')
    costs = [float(r.get('reserved_cost_usd') or r.get('estimated_cost_usd') or 0) for r in new]
    if any(r['model'] != MODEL for r in new) or any(
            not math.isfinite(cost) or cost < 0 for cost in costs):
        raise ValueError('Guest accounting identity/value differs')
    charge = sum(Decimal(r.get('reserved_cost_usd') or r.get('estimated_cost_usd') or '0')
                 for r in new)
    if charge > reserve:
        raise ValueError('Guest charge exceeds whole-probe reservation')
    with ledger.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = list(csv.DictReader(ledger.open()))
        reservation = next(r for r in rows if r['call_id'] == call_id)
        if reservation['status'] != 'native_probe_reserved':
            raise ValueError('Single probe accounting already reconciled')
        if Decimal(reservation['reserved_cost_usd']) != reserve:
            raise ValueError('Reconciliation differs from original reserved request bound')
        if {r['call_id'] for r in rows} & {r['call_id'] for r in new}:
            raise ValueError('Guest accounting overlaps host calls')
        reservation.update(status='native_probe_reconciled', reserved_cost_usd='',
                           estimated_cost_usd='0')
        rows.extend(new)
        _write(ledger, rows)
    return new


def _write(path: Path, rows: list[dict]) -> None:
    temporary = path.with_suffix('.csv.tmp')
    with temporary.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
