"""Exercise the actual product review, block, repair/retest and approval routes."""
from __future__ import annotations

import json
import time
import urllib.request
import uuid
from pathlib import Path

from scripts.core_app_workflow import ledger
from skillguard.core import CoreWorkspace
from skillguard.review.snapshot import digest


def workflow(root: Path, port=8768, resume: Path | None = None, *, accept_held_verdict=False):
    base = f'http://127.0.0.1:{port}'
    folder = root / 'results/integration' / ('security-product-' + uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    report = {'run_id': folder.name, 'passed': False, 'steps': [], 'before': ledger(root),
        'scope': 'Actual app security-review workflow; authored unsafe sample and known repair',
        'maximum_new_requests': 27}
    frozen = {str(p): digest(p.read_bytes()) for tree in ('scripts', 'skillguard')
              for p in (root / tree).rglob('*.py')}
    frozen.update({str(p): digest(p.read_bytes()) for p in (root / 'skillguard/ui').glob('core.*')})
    report['runtime_sha256'] = frozen

    def save():
        raw = json.dumps(report, indent=2) + '\n'
        (folder / 'workflow.json').write_text(raw)
        (root / 'results/security-product-latest.json').write_text(raw)

    def state():
        with urllib.request.urlopen(base + '/api/state', timeout=30) as response:
            return json.load(response)

    def action(name, failure=False, **payload):
        before = state()
        if (before.get('job') or {}).get('status') == 'running':
            raise ValueError('Another app action is running')
        request = urllib.request.Request(base + '/api/action',
            data=json.dumps({'action': name, **payload}).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'Origin': base,
                     'X-SkillGuard-CSRF': before['csrf']})
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 202
        deadline = time.monotonic() + 2400
        last_message = None
        while time.monotonic() < deadline:
            current = state()
            job = current.get('job') or {}
            if job.get('message') and job['message'] != last_message:
                print(job['message'], flush=True)
                last_message = job['message']
            if job.get('status') != 'running':
                report['steps'].append({'step': name, 'result': job})
                save()
                print(name + ': ' + job['status'], flush=True)
                if job.get('status') != ('failed' if failure else 'done'):
                    raise ValueError('App action did not complete: ' + name)
                return current
            time.sleep(2)
        raise TimeoutError('App action timed out; preserve native evidence and claims')

    def pending(current):
        rows = [r for r in current['reviews'] if r['pending']]
        if len(rows) != 1:
            raise ValueError('Exactly one paused skill required')
        return rows[0]

    try:
        initial = state()
        if resume is not None:
            resume = resume.resolve()
            if not resume.is_relative_to(root / 'results/integration'):
                raise ValueError('Local retained product workflow required')
            raw = resume.read_bytes()
            prior = json.loads(raw)
            current = pending(initial)
            if (prior.get('passed') is not False
                    or current['id'] != prior.get('repaired_review')
                    or initial['active'] != prior['original_active']
                    or prior['after'] != ledger(root)):
                raise ValueError('Cannot continue a changed product review or ledger')
            original = prior['original_active']
            report.update(continuation_of=str(resume), continuation_sha256=digest(raw),
                before=prior['before'], original_active=original,
                original_review_ids=prior['original_review_ids'], steps=prior['steps'],
                blocked_review=prior['blocked_review'], blocked_result=prior['blocked_result'],
                preserved_incomplete_review=prior['repaired_result'], maximum_new_requests=40)
            operation = ('escalate_security' if current['security'].get('can_escalate') else
                         'resume_security' if prior['repaired_result'].get('verified_probes', 0)
                         else 'review_security')
            if (current['security'].get('can_accept_hold')
                    and current['security'].get('previous_model_reviews')):
                repaired = current
                report['steps'].append({'step': 'reuse_complete_held_review',
                                        'new_model_requests': 0})
            else:
                repaired = pending(action(operation, review_id=current['id']))
        else:
            if any(r['pending'] for r in initial['reviews']):
                raise ValueError('An existing review must be preserved and resolved first')
            original = initial['active']
            report['original_active'] = original
            report['original_review_ids'] = [r['id'] for r in initial['reviews']]
            unsafe = pending(action('unsafe'))
            action('approve', failure=True, review_id=unsafe['id'], revision=unsafe['revision'],
                   acknowledge_limits=True)
            checked = pending(action('review_security', review_id=unsafe['id']))
            if checked['security'].get('decision') != 'blocked' or checked['eligible']:
                raise ValueError('Unsafe staged skill was not blocked by its security review')
            if not checked['security'].get('model_review'):
                raise ValueError('Unsafe review lacks an actual model evidence recommendation')
            report['blocked_review'] = checked['id']
            report['blocked_result'] = checked['security']
            action('approve', failure=True, review_id=checked['id'], revision=checked['revision'],
                   acknowledge_limits=True)
            repaired = pending(action('repair_and_review', review_id=checked['id'],
                                      revision=checked['revision']))
        report['repaired_review'] = repaired['id']
        report['repaired_result'] = repaired['security']
        exception = accept_held_verdict and repaired['security'].get('can_accept_hold') is True
        if (not (repaired['security'].get('decision') == 'restricted_pass' and repaired['eligible']
                 or exception) or repaired['security'].get('verified_probes') != 4):
            raise ValueError('Repaired skill has not passed the full security-review workflow')
        approval = {'accept_model_hold': True, 'operator_reason':
            'Authorized bounded product demonstration: all four native agent probes and '
            'source checks passed. Accept the retained model hold only inside the tested '
            'receipt sandbox. This is a human exception, not a model security pass.'
            } if exception else {}
        installed = action('approve', review_id=repaired['id'], revision=repaired['revision'],
                           acknowledge_limits=True, **approval)['active']
        outcome = 'operator_approved_hold' if exception else 'restricted_pass'
        report['approval_outcome'] = outcome
        report['model_hold_preserved'] = exception
        if installed.get('security_decision') != outcome:
            raise ValueError('Installed manifest lacks the exact security decision')
        report['installed'] = installed
        if original:
            restored = action('rollback', expected_active=installed['id'])['active']
            if restored != original:
                raise ValueError('Rollback failed to restore the exact original version')
            final = action('rollback', expected_active=original['id'])
        else:
            final = state()
        if final['active'] != installed or any(r['pending'] for r in final['reviews']):
            raise ValueError('Security-reviewed version not selected or pending writes remain')
        if not set(report['original_review_ids']) <= {r['id'] for r in final['reviews']}:
            raise ValueError('Original review history was not preserved')
        if any(digest(Path(p).read_bytes()) != sha for p, sha in frozen.items()):
            raise ValueError('Product runtime changed during the native review')
        workspace = CoreWorkspace(root, root / 'results/core')
        for vid in workspace.installed()['versions']:
            workspace.version(vid)
        report['after'] = ledger(root)
        count = report['after']['completed_requests'] - report['before']['completed_requests']
        if (not 3 <= count <= report['maximum_new_requests']
                or report['after']['accounted_usd'] > .75):
            raise ValueError('Observed request count or aggregate cap differs')
        report.update(passed=True, new_model_requests=count, final_active=installed,
                      previous=final['previous'], all_prior_reviews_preserved=True,
                      runtime_preserved=True, pending_count=0)
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
    finally:
        report['after'] = ledger(root)
        save()
    return report


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--accept-held-verdict', action='store_true',
                        help='Explicitly accept a model hold only with four passing native probes')
    args = parser.parse_args()
    result = workflow(Path(__file__).resolve().parents[1], resume=args.resume,
                      accept_held_verdict=args.accept_held_verdict)
    print(json.dumps({k: result.get(k) for k in ('run_id', 'passed', 'error', 'after',
                                               'new_model_requests')}, indent=2))
    if not result['passed']:
        raise SystemExit(1)
