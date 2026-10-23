"""Read the current ledger without changing archived evaluation totals or holds."""
from __future__ import annotations

import csv
import fcntl
from decimal import Decimal, InvalidOperation
from pathlib import Path

from skillguard.models.spending_policy import project_cap


def read(path: Path) -> dict:
    cap = project_cap(path.parent)
    if not path.exists():
        return {'available': False, 'cap_usd': cap}
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        with path.open() as source:
            rows = list(csv.DictReader(source))
    try:
        values = [(Decimal(r['estimated_cost_usd'] or '0'),
                   Decimal(r['reserved_cost_usd'] or '0')) for r in rows]
        if any(not n.is_finite() or n < 0 for pair in values for n in pair):
            raise ValueError('Invalid inference ledger')
    except (KeyError, InvalidOperation) as error:
        raise ValueError('Invalid inference ledger') from error
    usage = sum((p[0] for p in values), Decimal(0))
    reserved = sum((p[1] for p in values), Decimal(0))
    return {'available': True, 'cap_usd': cap, 'estimated_cost_usd': float(usage),
            'reserved_usd': float(reserved), 'accounted_usd': float(usage + reserved),
            'completed_requests': sum(r['status'] == 'completed' for r in rows)}
