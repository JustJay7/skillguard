"""Exercise the running local app, including two fresh bounded agent executions.

This changes only the app's restricted installation. No parser-only approval bypass
is used. Each step is retained before proceeding; failures are never auto-retried.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path

from scripts.core_workflow import RECEIPT
from skillguard.core import CoreWorkspace
from skillguard.review.snapshot import digest, snapshot_digest


def ledger(root: Path) -> dict:
    rows = list(csv.DictReader((root / 'results/cost_log.csv').open()))
    estimated = sum((Decimal(r['estimated_cost_usd'] or '0') for r in rows), Decimal(0))
    reserved = sum((Decimal(r['reserved_cost_usd'] or '0') for r in rows), Decimal(0))
    return {'completed_requests': sum(r['status'] == 'completed' for r in rows),
            'estimated_cost_usd': float(estimated), 'unknown_reserved_usd': float(reserved),
            'accounted_usd': float(estimated + reserved),
            'sha256': digest((root / 'results/cost_log.csv').read_bytes())}


def workflow(root: Path, *, port=8768, resume: Path | None = None) -> dict:
    base = f'http://127.0.0.1:{port}'
    folder = root / 'results/integration' / ('core-app-' + uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    report = {'run_id': folder.name, 'passed': False, 'steps': [], 'before': ledger(root),
              'scope': 'Actual local HTTP app; fixed fictional task; restricted installation',
              'maximum_new_model_requests': 12}
    workspace = CoreWorkspace(root, root / 'results/core')
    frozen_paths = [*(root / 'skillguard').rglob('*.py'), *(root / 'scripts').glob('*.py'),
                    *(root / 'skillguard/ui').glob('core.*'),
                    *(root / 'skills/repaired-v8/receipt-organizer').rglob('*')]
    frozen = {str(p): digest(p.read_bytes()) for p in frozen_paths if p.is_file()}
    report['runtime_sha256'] = frozen

    def save():
        raw = json.dumps(report, indent=2) + '\n'
        (folder / 'workflow.json').write_text(raw)
        (root / 'results/core-app-workflow-latest.json').write_text(raw)

    def state():
        with urllib.request.urlopen(base + '/api/state', timeout=30) as response:
            return json.load(response)

    def record(step, value):
        report['steps'].append({'step': step, 'result': value})
        save()
        print(step, flush=True)

    def action(name, *, failure=False, **payload):
        current = state()
        if (current.get('job') or {}).get('status') == 'running':
            raise ValueError('An app operation is already running')
        request = urllib.request.Request(base + '/api/action',
            data=json.dumps({'action': name, **payload}).encode(),
            headers={'Content-Type': 'application/json', 'Origin': base,
                     'X-SkillGuard-CSRF': current['csrf']}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 202:
                raise ValueError('App refused the action')
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            current = state()
            job = current.get('job') or {}
            if job.get('status') != 'running':
                record(name, job)
                if job.get('action') != name or job.get('status') != (
                        'failed' if failure else 'done'):
                    raise ValueError('App action did not reach its expected outcome: ' + name)
                return current
            time.sleep(2)
        raise TimeoutError('App operation timed out; evidence and claims retained')

    def pending(current):
        items = [r for r in current['reviews'] if r['pending']]
        if len(items) != 1:
            raise ValueError('Exactly one pending native review required')
        return items[0]

    try:
        initial = state()
        if not initial['active'] or any(r['pending'] for r in initial['reviews']):
            raise ValueError('Existing installation with no pending writes required')
        expected = snapshot_digest(root / 'skills/repaired-v8/receipt-organizer')
        if resume is not None:
            resume = resume.resolve()
            if not resume.is_relative_to(root / 'results/integration'):
                raise ValueError('Local retained workflow required for continuation')
            prior_raw = resume.read_bytes()
            prior = json.loads(prior_raw)
            last = prior['steps'][-1]
            if (prior.get('passed') is not False or last['step'] != 'run_agent'
                    or last['result'].get('error') != 'The approved probe was already consumed'
                    or prior['after'] != ledger(root)
                    or initial['active'] != prior['repaired_active']):
                raise ValueError('Only the proven zero-call request-identity stop can continue')
            old, installed = prior['initial_active'], prior['repaired_active']
            workspace.version(old['id'])
            workspace.version(installed['id'])
            if installed['candidate_sha256'] != expected:
                raise ValueError('Repaired candidate changed before continuation')
            report.update(continuation_of=str(resume), continuation_sha256=digest(prior_raw),
                before=prior['before'], steps=prior['steps'],
                initial_active=old, initial_review_ids=prior['initial_review_ids'],
                review_agent_run=prior['review_agent_run'], repaired_active=installed,
                continuation_reason='Fresh request identity; no claim reset or paid retry')
            baseline = prior['steps'][0]['result']['result']['receipt']
            record('continue after zero-call request-identity stop', {'model_requests': 0})
        else:
            old = initial['active']
            if workspace.installed()['active'] != old['id']:
                raise ValueError('HTTP app is not using the intended main workspace')
            workspace.version(old['id'])
            report['initial_active'] = old
            report['initial_review_ids'] = [r['id'] for r in initial['reviews']]
            baseline = action('run', text=RECEIPT)['job']['result']['receipt']
            bad = pending(action('unsafe'))
            bad = pending(action('test', review_id=bad['id']))
            if bad['eligible'] or bad['test']['passed'] is not False:
                raise ValueError('Planted unsafe skill was not blocked')
            action('approve', failure=True, review_id=bad['id'], revision=bad['revision'],
                   acknowledge_limits=True)
            action('reject', review_id=bad['id'], revision=bad['revision'])
            repaired = pending(action('repaired'))
            expected = snapshot_digest(root / 'skills/repaired-v8/receipt-organizer')
            if repaired['candidate_sha256'] != expected:
                raise ValueError('App did not stage the exact repaired candidate')
            repaired = pending(action('test', review_id=repaired['id']))
            if not repaired['parser_eligible']:
                raise ValueError('Repaired source/parser checks failed')
            action('approve', failure=True, review_id=repaired['id'], revision=repaired['revision'],
                   acknowledge_limits=True)
            before_agent_revision = repaired['revision']
            repaired = pending(action('test_agent', review_id=repaired['id']))
            if not repaired['eligible']:
                raise ValueError('Actual agent did not pass on the repaired candidate')
            report['review_agent_run'] = repaired['agent']['run_id']
            action('approve', failure=True, review_id=repaired['id'],
                   revision=before_agent_revision,
                   acknowledge_limits=True)
            installed = action('approve', review_id=repaired['id'], revision=repaired['revision'],
                               acknowledge_limits=True)['active']
            if installed['candidate_sha256'] != expected or not installed['agent_verified']:
                raise ValueError('Installed source differs from the tested repaired candidate')
            report['repaired_active'] = installed
        result = action('run_agent', expected_active=installed['id'])['job']['result']
        report['installed_agent'] = result
        if (result['candidate_sha256'] != expected or result['version'] != installed['id']
                or result['answer']['receipt']['total'] != 23
                or result['run_id'] == report['review_agent_run']
                or not result['agent_completion_confirmed']
                or not all(result['skill_use'][k] for k in (
                    'guide_before_receipt_observed', 'guide_after_receipt_observed'))):
            raise ValueError('Installed agent output/source/read-order proof differs')
        local = action('run', text=RECEIPT)['job']['result']
        if local['receipt'] != baseline or local['version'] != installed['id']:
            raise ValueError('Installed repaired parser differs on the receipt contract')
        restored = action('rollback', expected_active=installed['id'])['active']
        if restored != old:
            raise ValueError('Rollback failed to select the exact original version')
        original = action('run', text=RECEIPT)['job']['result']
        if original['receipt'] != baseline or original['version'] != old['id']:
            raise ValueError('Original version did not reproduce its output after rollback')
        action('run_agent', failure=True, expected_active=installed['id'])
        current = action('rollback', expected_active=old['id'])
        if current['active'] != installed:
            raise ValueError('Failed to restore the tested repaired installation')
        record('final repaired parser use', action('run', text=RECEIPT)['job']['result'])
        if any(digest(Path(p).read_bytes()) != sha for p, sha in frozen.items()):
            raise ValueError('Runtime or repaired source changed during the workflow')
        if not set(report['initial_review_ids']).issubset(r['id'] for r in current['reviews']):
            raise ValueError('Existing review history was lost')
        report['after'] = ledger(root)
        requests = report['after']['completed_requests'] - report['before']['completed_requests']
        report['new_model_requests'] = requests
        if not 2 <= requests <= 12 or report['after']['accounted_usd'] > .75:
            raise ValueError('Request count or aggregate budget differs')
        report.update(passed=True, final_active=current['active'],
                      final_previous=current['previous'], source_preserved=True,
                      review_preserved=True,
                      pending_count=sum(r['pending'] for r in current['reviews']))
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
    finally:
        report['after'] = ledger(root)
        save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8768)
    parser.add_argument('--resume', type=Path)
    args = parser.parse_args()
    result = workflow(Path(__file__).resolve().parents[1], port=args.port, resume=args.resume)
    print(json.dumps({k: v for k, v in result.items() if k not in {'steps', 'runtime_sha256'}},
                     indent=2))
    if not result['passed']:
        raise SystemExit(1)
