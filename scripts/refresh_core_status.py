from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from skillguard.review.store import ReviewStore
from skillguard.ui.server import review_summary


def refresh(root: Path, *, client_date: str, test_console: Path) -> dict:
    parent_path = root / 'results/integration/local-parser-8fc64684/preparation.json'
    parent = json.loads(parent_path.read_text())
    store = ReviewStore(Path(parent['store']))
    summary = review_summary(store, parent['review_id'])
    rows = list(csv.DictReader((root / 'results/cost_log.csv').open()))
    console = test_console.read_text()
    counts = re.findall(r'(\d+) passed', console)
    if not counts or 'All checks passed!' not in console:
        raise ValueError('A successful full offline suite and lint result are required')
    workflow = json.loads((root / 'results/receipt-agent-workflow-latest.json').read_text())
    live = json.loads((root / 'results/receipt-agent-live-latest.json').read_text())
    enforced_live = json.loads(
        (root / 'results/receipt-agent-enforced-live-latest.json').read_text())
    recorded = json.loads((root / 'results/receipt-agent-recorded-latest.json').read_text())
    enforced = json.loads((root / 'results/receipt-agent-enforced-latest.json').read_text())
    output = root / 'results/receipt-core-review-latest.json'
    value = json.loads(output.read_text())
    value.pop('model_calls_this_turn', None)
    value.update(verified_at=datetime.now(UTC).isoformat(), verified_on_client_date=client_date,
        scope='Bounded native parser and agent review; complete product unfinished',
        complete=False, activation_permitted=False, pending_preserved=False,
        pending_removed=summary['pending_removed'], archive_preserved=summary['archive_preserved'],
        active_skill_absent=workflow['active_skill_absent'],
        final_review={**value['final_review'],
            'decision': store.get(parent['review_id'])['latest']['decision'],
            'evidence': store.evidence(parent['review_id'])}, model_advice_current=False,
        accounted_completed_requests=sum(r['status'] == 'completed' for r in rows),
        estimated_inference_cost_usd=sum(float(r.get('estimated_cost_usd') or 0) for r in rows),
        unknown_cost_reserved_usd=sum(float(r.get('reserved_cost_usd') or 0) for r in rows),
        runner_states=workflow['runner_states'], native_agent_workflow=workflow,
        native_agent_live_trial=live, native_agent_recorded_replay=recorded,
        native_agent_enforced_replay=enforced, native_agent_enforced_live_trial=enforced_live,
        local_review_summary=summary,
        local_review_ui={'url': 'http://127.0.0.1:8768/', 'mode': 'read-only',
                         'api_verified': True, 'visual_verified': False},
        verification={'command': 'make test', 'tests_passed': int(counts[-1]), 'ruff': 'clean'},
        remaining=['Fresh enforced live attack/control set and Skill Lift',
            'Broader file/process/descriptor/IP/image/privilege and capture evidence',
            'Safe activation and installed rollback', 'Matched benchmark comparison',
            'Visual verification, hosted demo, video, public repository and submission'],
        commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip())
    output.write_text(json.dumps(value, indent=2) + '\n')
    shared = root.parent / 'outputs/skillguard-core-verification.json'
    status = json.loads(shared.read_text())
    status.update(status='Native agent/OpenShell milestone; complete product unfinished',
                  verified_at=value['verified_at'], frozen_receipt_repair=value)
    shared.write_text(json.dumps(status, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--client-date', required=True)
    parser.add_argument('--test-console', type=Path, required=True)
    args = parser.parse_args()
    result = refresh(Path(__file__).resolve().parents[1], client_date=args.client_date,
                     test_console=args.test_console)
    print(json.dumps({k: result[k] for k in ('decision', 'pending_removed',
        'archive_preserved', 'activation_permitted', 'revision')}, indent=2))
