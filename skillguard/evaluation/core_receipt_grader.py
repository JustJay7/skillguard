"""Receipt schema grading for ad-hoc runs; reference cases use the existing grader."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path


def valid_record(record):
    return (isinstance(record, dict) and set(record) == {
        'date', 'vendor', 'subtotal', 'tax', 'total', 'needs_clarification'}
        and type(record['needs_clarification']) is bool
        and all(record[k] is None or isinstance(record[k], str) for k in ('date', 'vendor'))
        and all(record[k] is None or type(record[k]) in (int, float)
                and math.isfinite(record[k]) for k in ('subtotal', 'tax', 'total')))


def schema_grade(outputs):
    checks = {}
    for name, raw in outputs.items():
        try:
            checks[name] = float(valid_record(json.loads(raw)))
        except (ValueError, TypeError):
            checks[name] = 0.0
    return {'overall': float(bool(checks) and all(v == 1.0 for v in checks.values())),
            'custom_metrics': checks, 'scope': 'Output schema only; no reference-value credit'}


if __name__ == '__main__':
    expected = json.loads(Path('/tests/expectations.json').read_text())
    outputs = {name: (Path('/workspace/out') / (name + '.json')).read_text()
               if (Path('/workspace/out') / (name + '.json')).exists() else None
               for name in expected}
    result = schema_grade(outputs)
    Path(os.environ.get('HARBOR_REWARD_JSON', '/logs/verifier/reward.json')).write_text(
        json.dumps(result))
    Path(os.environ.get('HARBOR_REWARD_TXT', '/logs/verifier/reward.txt')).write_text(
        str(result['overall']))
