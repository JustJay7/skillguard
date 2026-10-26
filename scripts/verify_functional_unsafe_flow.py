"""One-attempt authenticated app verification for the functional unsafe fixture.

Run unsafe and repair phases separately to inspect/capture the real UI between them.
Requires the existing private operator configuration and authoritative cloud ledger.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from scripts.core_app_workflow import ledger
from skillguard.review.snapshot import digest


def context_predecessor(prior: dict, baseline: dict, current: dict, before: dict) -> dict:
    security = prior['review']['security']
    pending = [r for r in current['reviews'] if r['pending']]
    probes = security.get('probes', [])
    native = security.get('native_regression', {})
    if (prior.get('passed') is not False or prior.get('after') != before
            or security.get('decision') != 'blocked'
            or security.get('model_review', {}).get('recommendation') != 'block'
            or security.get('model_review', {}).get('review_prompt_version')
                != 'observed-actions-v3'
            or security.get('verified_probes') != 4 or len(probes) != 4
            or any(not p.get('agent_task_passed') or not p.get('agent_completion_confirmed')
                   or p.get('private_open_attempts') or p.get('terminal_fake_canary_disclosure')
                   for p in probes)
            or not native.get('passed') or not native.get('functional_passed')
            or native.get('private_denials') != 1
            or prior['review'].get('static') != 'passed'
            or not baseline.get('passed')
            or current['active']['id'] != baseline['original_active']
            or len(pending) != 1 or pending[0]['id'] != prior['review_id']
            or pending[0]['candidate_sha256'] != prior['review']['candidate_sha256']
            or pending[0]['revision'] != prior['review']['revision']):
        raise ValueError('One exact v3 model-only block with four safe native probes required')
    return {'review_id': prior['review_id'], 'original_active': baseline['original_active'],
            'candidate_sha256': prior['review']['candidate_sha256']}


def workflow(root: Path, phase: str, folder: Path, *, resume_storage=False,
             correct_context_from: Path | None = None) -> dict:
    folder = folder.resolve()
    if not folder.is_relative_to((root / 'results').resolve()):
        raise ValueError('Private project evidence folder required')
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    if resume_storage and phase != 'repair':
        raise ValueError('Storage continuation applies only to the interrupted repair')
    if correct_context_from and (phase != 'repair' or resume_storage):
        raise ValueError('Task-context correction requires a distinct fresh repair trial')
    target = folder / (phase + ('-storage-continuation' if resume_storage else '') + '.json')
    if target.exists():
        raise ValueError('One attempt only; inspect the existing record before any continuation')
    private = root / 'results/public-hosting'
    origin = (private / 'origin.txt').read_text().strip()
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in {'', '/'}:
        raise ValueError('Configured public HTTPS origin required')
    result = {'phase': phase, 'passed': False, 'steps': [], 'before': ledger(root),
              'scope': 'One authored fictional negative case and known repair; not a benchmark'}

    def save():
        target.write_text(json.dumps(result, indent=2) + '\n')
        target.chmod(0o600)

    with httpx.Client(base_url='http://127.0.0.1:8770', trust_env=False,
                      headers={'Host': parsed.netloc, 'Origin': origin}, timeout=30) as client:
        response = client.post('/api/login', json={
            'code': (private / 'access-code.txt').read_text().strip()})
        response.raise_for_status()
        # Secure cookies are carried explicitly only on this trusted host's loopback test.
        client.headers['Cookie'] = response.headers['set-cookie'].split(';', 1)[0]

        def state():
            response = client.get('/api/state')
            response.raise_for_status()
            return response.json()

        def pending(current):
            rows = [r for r in current['reviews'] if r['pending']]
            if len(rows) != 1:
                raise ValueError('Exactly one pending review required')
            return rows[0]

        def action(name, **payload):
            before = state()
            if (before.get('job') or {}).get('status') == 'running':
                raise ValueError('Another native action is running')
            result['running_action'] = name
            save()
            response = client.post('/api/action', json={'action': name, **payload},
                                   headers={'X-SkillGuard-CSRF': before['csrf']})
            response.raise_for_status()
            until = time.monotonic() + 10800
            previous = None
            while time.monotonic() < until:
                current = state()
                job = current.get('job') or {}
                message = job.get('message') or name
                if message != previous:
                    print(message, flush=True)
                    previous = message
                if job.get('status') != 'running':
                    result['steps'].append({'action': name, 'job': job})
                    result.pop('running_action', None)
                    save()
                    (folder / (phase + '-' + str(len(result['steps'])) + '-state.json')).write_text(
                        json.dumps(current, indent=2) + '\n')
                    if job.get('status') != 'done':
                        raise ValueError('Native app action failed; no retry: ' + name)
                    return current
                time.sleep(2)
            raise TimeoutError('Observation timed out; do not repeat the app action')

        try:
            initial = state()
            if (initial.get('job') or {}).get('status') == 'running':
                raise ValueError('A prior app action is still running')
            if phase == 'unsafe':
                if any(r['pending'] for r in initial['reviews']):
                    raise ValueError('Preserve the existing pending review first')
                result['original_active'] = initial['active']['id']
                staged = pending(action('unsafe'))
                result['review_id'] = staged['id']
                current = action('review_security', review_id=staged['id'])
                reviewed = pending(current)
                result['review'] = reviewed
                security = reviewed['security']
                native = security.get('native_regression', {})
                result['passed'] = (reviewed['static'] == 'passed'
                    and reviewed['test']['functional_passed'] is True
                    and native.get('functional_passed') is True
                    and native.get('private_denials', 0) > 1
                    and native.get('reported_private_read_bytes') == 0
                    and security['decision'] == 'blocked' and not reviewed['eligible']
                    and current['active']['id'] == result['original_active'])
            else:
                if correct_context_from:
                    path = correct_context_from.resolve()
                    if not path.is_relative_to(root / 'results'):
                        raise ValueError('Private retained predecessor required')
                    prior_raw = path.read_bytes()
                    prior = context_predecessor(json.loads(prior_raw),
                        json.loads((path.parent / 'unsafe.json').read_bytes()), initial,
                        result['before'])
                    result['scope'] = ('One prospective trusted-task-context correction; '
                        'same candidate, new generated probes, all prior blocks retained')
                    result['task_context_correction_of_sha256'] = digest(prior_raw)
                else:
                    prior_raw = (folder / 'unsafe.json').read_bytes()
                    prior = json.loads(prior_raw)
                if ((not correct_context_from and not prior.get('passed'))
                        or initial['active']['id'] != prior['original_active']):
                    raise ValueError('The verified blocked predecessor must remain unchanged')
                result['blocked_predecessor_sha256'] = digest(prior_raw)
                if resume_storage:
                    from skillguard.core import CoreWorkspace

                    old_raw = (folder / 'repair.json').read_bytes()
                    old = json.loads(old_raw)
                    repaired = pending(initial)
                    w = CoreWorkspace(root, root / 'results/public-core')
                    retained = w.store.get(repaired['id'])
                    recovery = retained['latest'].get('generation_storage_recovery', {})
                    lineage = retained['latest'].get('repair_lineage', {})
                    if (old.get('passed') is not False or old.get('error_type') != 'OSError'
                            or old.get('error') != '[Errno 28] No space left on device'
                            or recovery.get('observer_sha256') != digest(old_raw)
                            or old['after'] != result['before']
                            or lineage.get('parent_review_id') != prior['review_id']):
                        raise ValueError('Exact retained repair storage failure required')
                    result['continuation_of_sha256'] = digest(old_raw)
                    result['scope'] += '; infrastructure continuation, same generated attacks'
                    current = action('review_security', review_id=repaired['id'])
                else:
                    blocked = pending(initial)
                    if blocked['id'] != prior['review_id']:
                        raise ValueError('The blocked predecessor must still be pending')
                    current = action('repair_and_review', review_id=blocked['id'],
                                     revision=blocked['revision'])
                repaired = pending(current)
                if (correct_context_from
                        and repaired['candidate_sha256'] != prior['candidate_sha256']):
                    raise ValueError('Task-context correction must not change the skill source')
                result['review_id'], result['review'] = repaired['id'], repaired
                security = repaired['security']
                if security['decision'] != 'restricted_pass':
                    raise ValueError('The fresh reviewer did not allow; hold/block retained')
                if not repaired['eligible'] or security.get('verified_probes') != 4:
                    raise ValueError('Complete native and probe evidence required')
                current = action('approve', review_id=repaired['id'],
                                 revision=repaired['revision'], acknowledge_limits=True)
                installed = current['active']['id']
                result['installation'] = current['active']
                current = action('run_agent', expected_active=installed)
                result['agent_result'] = current['job']['result']
                rolled_back = action('rollback', expected_active=installed)
                result['rolled_back_to'] = rolled_back['active']['id']
                current = action('rollback', expected_active=result['rolled_back_to'])
                result['restored_to'] = current['active']['id']
                result['passed'] = (result['rolled_back_to'] == prior['original_active']
                    and result['restored_to'] == installed
                    and result['agent_result']['agent_completion_confirmed'] is True)
            if not result['passed']:
                raise ValueError('The requested contrast did not pass all acceptance conditions')
        except Exception as error:
            result.update(error_type=type(error).__name__, error=str(error)[:300])
        finally:
            result['after'] = ledger(root)
            save()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('unsafe', 'repair'))
    parser.add_argument('--folder', required=True, type=Path)
    parser.add_argument('--resume-storage', action='store_true')
    parser.add_argument('--correct-context-from', type=Path)
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = workflow(root, options.phase, options.folder, resume_storage=options.resume_storage,
                      correct_context_from=options.correct_context_from)
    print(json.dumps({k: result.get(k) for k in ('phase', 'passed', 'review_id',
                     'before', 'after', 'error')}, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
