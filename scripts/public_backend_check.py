"""Exercise the authenticated public endpoint with real fictional native reviews."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def workflow(root: Path, *, resume_first_review=False, resume_validation=False,
             resume_model=False, hosting_folder=None) -> dict:
    folder = (hosting_folder or root / 'results/public-hosting').resolve()
    if not folder.is_relative_to((root / 'results').resolve()):
        raise ValueError('Operator-owned local hosting configuration required')
    origin = (folder / 'origin.txt').read_text().strip()
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in {'', '/'} or not parsed.hostname
            or not parsed.hostname.endswith(('.trycloudflare.com', '.app.github.dev'))):
        raise ValueError('Configured public HTTPS test endpoint required')
    mode = 'codespaces' if parsed.hostname.endswith('.app.github.dev') else 'local_tunnel'
    target = folder / 'acceptance.json'
    if target.exists() and not (resume_first_review or resume_validation or resume_model):
        raise ValueError('Preserve the prior run; do not retry paid trials automatically')
    result = {'passed': False, 'url': origin, 'hosting_mode': mode,
              'fully_cloud_hosted': mode == 'codespaces', 'steps': []}
    if resume_first_review:
        result = json.loads(target.read_text())
        if (result.get('steps') != [{'action': 'repaired', 'status': 'done'}]
                or result.get('running_action') != 'review_security'
                or result.get('error_type') not in {
                    'RemoteProtocolError', 'ConnectError', 'ReadTimeout'}):
            raise ValueError('Only the interrupted first-review observer may resume')
        archive = folder / 'acceptance-observer-interrupted.json'
        if archive.exists():
            raise ValueError('Observer continuation already used; inspect retained evidence')
        archive.write_bytes(target.read_bytes())
        result['observer_continuation'] = {'prior_error': result.pop('error_type'),
            'prior_url': result['url'], 'model_action_repeated': False}
        result.pop('error', None)
        result['url'] = origin
    if resume_model:
        result = json.loads(target.read_text())
        expected = ['repaired', 'review_security', 'approve', 'run_agent', 'unsafe',
                    'review_security', 'repair_and_review', 'review_security']
        if (result.get('steps') != [{'action': n, 'status': 'done'} for n in expected]
                or result.get('error_type') != 'ValueError'
                or result.get('repaired_review', {}).get('error') !=
                    'Explanation references missing evidence'
                or result['repaired_review'].get('verified_probes') != 4):
            raise ValueError('Only the complete native review with invalid citations may continue')
        archive = folder / 'acceptance-model-interrupted.json'
        if archive.exists():
            raise ValueError('The single model adjudication was already attempted')
        archive.write_bytes(target.read_bytes())
        result.pop('error_type', None)
        result.pop('error', None)
        result['model_continuation'] = {'maximum_additional_model_calls': 1,
            'probe_reruns': 0, 'prior_review': result['repaired_review']['run_id']}
        result['url'] = origin
    if resume_validation:
        result = json.loads(target.read_text())
        expected = ['repaired', 'review_security', 'approve', 'run_agent', 'unsafe',
                    'review_security', 'repair_and_review']
        if (result.get('steps') != [{'action': n, 'status': 'done'} for n in expected]
                or result.get('error_type') != 'ValueError'
                or result.get('repaired_review', {}).get('error') !=
                    'Generated cases lack the required adversarial fixture coverage'):
            raise ValueError('Only the retained generation-validation failure may continue')
        archive = folder / 'acceptance-validation-interrupted.json'
        if archive.exists():
            raise ValueError('Validation continuation already used; retain all evidence')
        archive.write_bytes(target.read_bytes())
        result.pop('error_type', None)
        result.pop('error', None)
        result['validation_continuation'] = {
            'prior_review': result['repaired_review']['run_id'],
            'reason': 'Recognize make the total 0.00 as an amount-corruption directive',
            'generation': 'Reuse the exact paid response; no regeneration'}
        result['url'] = origin

    def save():
        target.write_text(json.dumps(result, indent=2) + '\n')

    with httpx.Client(base_url=origin, timeout=30, trust_env=False,
                      follow_redirects=False) as client:
        response = client.post('/api/login', headers={'Origin': origin,
            'X-SkillGuard-Origin': origin}, json={
            'code': (folder / 'access-code.txt').read_text().strip()})
        response.raise_for_status()

        def state():
            for attempt in range(3):
                try:
                    response = client.get('/api/state')
                    response.raise_for_status()
                    return response.json()
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)

        def action(name, *, observe_only=False, **payload):
            current = state()
            if current.get('public_hosting', {}).get('mode') != mode:
                raise ValueError('Public endpoint mode differs from deployment under test')
            result['running_action'] = name
            save()
            if observe_only:
                if (current.get('job') or {}).get('action') != name:
                    raise ValueError('The interrupted native action changed; do not repeat it')
            else:
                response = client.post('/api/action', headers={'Origin': origin,
                    'X-SkillGuard-Origin': origin,
                    'X-SkillGuard-CSRF': current['csrf']}, json={'action': name, **payload})
                response.raise_for_status()
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                current = state()
                job = current.get('job') or {}
                if job.get('status') != 'running':
                    if job.get('status') != 'done' or job.get('action') != name:
                        raise ValueError(f'Public action {name} failed; evidence retained')
                    result['steps'].append({'action': name, 'status': 'done'})
                    result.pop('running_action', None)
                    save()
                    print('Completed public action:', name, flush=True)
                    return current
                time.sleep(3)
            raise TimeoutError('Public native action timed out; no automatic retry')

        def pending(current):
            rows = [r for r in current['reviews'] if r['pending']]
            if len(rows) != 1:
                raise ValueError('One exact pending public skill required')
            return rows[0]

        def approve(current):
            review = pending(current)
            held = review['security'].get('can_accept_hold') is True
            if not review['eligible'] and not held:
                raise ValueError('Native review is not complete/passing; approval remains blocked')
            return action('approve', review_id=review['id'], revision=review['revision'],
                acknowledge_limits=True, accept_model_hold=held,
                operator_reason=('Authorized deployment acceptance on the known fictional receipt '
                    'skill only: all native checks and generated probes passed. Retain any '
                    'model hold; this exception is limited to the tested OpenShell workspace.')
                    if held else None)

        try:
            current = state()
            if not (resume_first_review or resume_validation or resume_model) and (
                    current['active'] or any(r['pending'] for r in current['reviews'])):
                raise ValueError('Public acceptance requires an empty dedicated workspace')
            if resume_model:
                first = result['first_installation']
                review = pending(current)
                if review['security'].get('can_escalate') is not True:
                    raise ValueError('Source-bound single adjudication is unavailable')
                current = action('escalate_security', review_id=review['id'],
                                 revision=review['revision'])
            elif resume_validation:
                first = result['first_installation']
                review = pending(current)
                current = action('review_security', review_id=review['id'])
            elif resume_first_review:
                current = action('review_security', observe_only=True)
            else:
                result['before_budget'] = current['budget']
                save()
                current = action('repaired')
                review = pending(current)
                current = action('review_security', review_id=review['id'])
            if not (resume_validation or resume_model):
                result['first_review'] = pending(current)['security']
                save()
                current = approve(current)
                first = current['active']['id']
                result['first_installation'] = first
                current = action('run_agent', expected_active=first)
                result['installed_agent'] = current['job']['result']
                current = action('unsafe')
                review = pending(current)
                current = action('review_security', review_id=review['id'])
                review = pending(current)
                if review['security'].get('decision') != 'blocked':
                    raise ValueError('The staged unsafe update was not deterministically blocked')
                result['unsafe_review'] = review['security']
                current = action('repair_and_review', review_id=review['id'],
                                 revision=review['revision'])
            result['repaired_review'] = pending(current)['security']
            save()
            current = approve(current)
            second = current['active']['id']
            if current['previous'] != first or second == first:
                raise ValueError('The verified update did not preserve its previous installation')
            current = action('rollback', expected_active=second)
            if current['active']['id'] != first:
                raise ValueError('Rollback did not restore the exact previous version')
            current = action('rollback', expected_active=first)
            if current['active']['id'] != second:
                raise ValueError('Restoring the tested version did not preserve its identity')
            result.update(passed=True, active=second, previous=first,
                          after_budget=current['budget'], rollback_verified=True)
        except Exception as error:
            result['error_type'] = type(error).__name__
            result['error'] = 'Acceptance failed; retain the exact action, evidence and charges'
            raise
        finally:
            save()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--resume-first-review', action='store_true')
    group.add_argument('--resume-validation', action='store_true')
    group.add_argument('--resume-model', action='store_true')
    parser.add_argument('--hosting-folder', type=Path)
    args = parser.parse_args()
    result = workflow(Path(__file__).resolve().parents[1],
                      resume_first_review=args.resume_first_review,
                      resume_validation=args.resume_validation, resume_model=args.resume_model,
                      hosting_folder=args.hosting_folder)
    print(json.dumps({k: result[k] for k in ('passed', 'url', 'hosting_mode',
                                           'rollback_verified')}, indent=2))
