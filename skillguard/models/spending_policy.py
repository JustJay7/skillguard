"""Operator-owned spending authorization; historical claims keep their own caps."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_CAP = .75


def validate_cap(value) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError('Invalid project spending authorization')
        cap = Decimal(str(value))
        if not cap.is_finite() or not 0 < cap <= 50:
            raise ValueError('Invalid project spending authorization')
    except (InvalidOperation, TypeError) as error:
        raise ValueError('Invalid project spending authorization') from error
    return float(cap)


def project_cap(results: Path) -> float:
    path = results / 'budget-authorization.json'
    if not path.exists():
        return DEFAULT_CAP
    if path.is_symlink():
        raise ValueError('Regular operator spending authorization required')
    try:
        value = json.loads(path.read_text())
        if not isinstance(value.get('authorization'), str) or not value['authorization'].strip():
            raise ValueError('Explicit spending authorization required')
        return validate_cap(value['aggregate_cap_usd'])
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid project spending authorization') from error


def proposal_cap(results: Path, value=DEFAULT_CAP) -> float:
    cap = validate_cap(value)
    if cap > project_cap(results):
        raise ValueError('Proposal exceeds the operator project spending authorization')
    return cap
