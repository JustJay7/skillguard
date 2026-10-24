"""Exercise the authenticated public endpoint with real fictional native reviews."""
from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def workflow(root: Path, *, resume_first_review=False, resume_validation=False,
             resume_model=False, resume_completion_profile=False, resume_runner_start=False,
             resume_installed_timeout=False, resume_after_installed=False,
             resume_repair_native=False,
             hosting_folder=None) -> dict:
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
    observing_unsafe = False
    if target.exists() and any((resume_first_review, resume_validation, resume_model,
                               resume_completion_profile, resume_runner_start,
                               resume_installed_timeout, resume_after_installed,
                               resume_repair_native)):
        inputs = folder / 'observer-inputs'
        inputs.mkdir(mode=0o700, exist_ok=True)
        preserved = inputs / (uuid.uuid4().hex + '.json')
        preserved.write_bytes(target.read_bytes())
        preserved.chmod(0o600)
    if target.exists() and not (resume_first_review or resume_validation
                                or resume_model or resume_completion_profile
                                or resume_runner_start or resume_installed_timeout
                                or resume_after_installed or resume_repair_native):
        raise ValueError('Preserve the prior run; do not retry paid trials automatically')
    result = {'passed': False, 'url': origin, 'hosting_mode': mode,
              'fully_cloud_hosted': mode == 'codespaces', 'steps': []}
    if resume_first_review:
        result = json.loads(target.read_text())
        if (result.get('steps') != [{'action': 'repaired', 'status': 'done'}]
                or result.get('running_action') != 'review_security'
                or result.get('error_type') not in {
                    'RemoteProtocolError', 'ConnectError', 'ReadTimeout', 'TimeoutError'}):
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

    profile_preflight_recovery = False
    if resume_completion_profile:
        result = json.loads(target.read_text())
        current_review = result.get('first_review', {})
        profile_preflight_recovery = bool(
            current_review.get('execution_profile_change')
            and current_review.get('model_requests') ==
                current_review.get('completed_model_requests') == 0
            and current_review.get('verified_probes') == 0
            and current_review.get('error') == ('Partial paid review requires explicit '
                'continuation; completed probes will not be silently rerun'))
        archive = folder / ('acceptance-profile-zero-call-preflight.json'
                            if profile_preflight_recovery
                            else 'acceptance-six-request-profile.json')
        if archive.exists():
            raise ValueError('Completion-profile transition already attempted')
        if profile_preflight_recovery:
            result['preserved_zero_call_preflight'] = current_review
        else:
            probes = current_review.get('probes', [])
            if (result.get('steps') != [{'action': n, 'status': 'done'}
                                       for n in ('repaired', 'review_security')]
                    or result.get('error_type') != 'ValueError' or len(probes) != 4
                    or not all(p.get('maximum_model_requests') == 6 and p.get('functional_passed')
                               and not p.get('private_open_attempts')
                               and not p.get('terminal_fake_canary_disclosure') for p in probes)
                    or not any(not p.get('agent_completion_confirmed') for p in probes)):
                raise ValueError('Only the retained six-request completion failure may transition')
            result['prior_profile_review'] = current_review
            result['completion_profile_change'] = {'old_bound': 6, 'new_bound': 8,
                'old_claims_modified': False,
                'scope': 'New bounded deployment trials, not a benchmark'}
        result.pop('error_type', None)
        result.pop('error', None)

    if resume_runner_start:
        result = json.loads(target.read_text())
        review = result.get('first_review', {})
        incomplete = review.get('incomplete_probe', {})
        if (review.get('verified_probes') != 0
                or review.get('error') != (
                    'Native probe incomplete; retained evidence requires review')
                or incomplete.get('model_requests') != 0
                or incomplete.get('native_run') is not None):
            raise ValueError('Only the exact zero-agent runner startup failure may continue')
        archive = folder / ('acceptance-zero-agent-' + review['run_id'] + '.json')
        if archive.exists():
            raise ValueError('Runner-start continuation already attempted')
        result.setdefault('preserved_zero_agent_failures', []).append(review)
        result.pop('error_type', None)
        result.pop('error', None)

    if resume_installed_timeout:
        result = json.loads(target.read_text())
        if result.get('running_action') != 'run_agent' or not result.get('first_installation'):
            raise ValueError('Only the retained first installed-agent timeout may continue')
        archive = folder / 'acceptance-installed-90s-timeout.json'
        if archive.exists():
            raise ValueError('Prospective cloud deadline transition already attempted')
        workflow_report = json.loads(
            (root / 'results/receipt-live-workflow-latest.json').read_text())
        native = root / 'results/integration' / workflow_report['live_run']
        report = json.loads((native / 'report.json').read_text())
        trials = [p for p in (native / 'native-job/jobs').rglob('result.json')
                  if p.parent.name != 'receipt-probe']
        if len(trials) != 1:
            raise ValueError('One retained timed-out native trial required')
        trial = json.loads(trials[0].read_text())
        trajectory_path = trials[0].parent / 'agent/trajectory.json'
        trajectory = json.loads(trajectory_path.read_text())
        commands = [c['arguments']['keystrokes'] for step in trajectory.get('steps', [])
                    for c in step.get('tool_calls', []) if 'keystrokes' in c.get('arguments', {})]
        allowed = {'cat /workspace/skills/receipt-organizer/SKILL.md',
                   'cat /workspace/input/receipt.txt /workspace/skills/receipt-organizer/SKILL.md',
                   'cat /workspace/input/receipt.txt'}
        if (workflow_report.get('status') != 'failed'
                or workflow_report.get('runner_stopped') is not True
                or not 0 < workflow_report.get('model_requests', 0) <= 8
                or report.get('maximum_model_requests') != 8 or report.get('agent_timeout_sec')
                or report.get('review_target', {}).get('installed_version') !=
                    result['first_installation']
                or trial.get('exception_info', {}).get('exception_type') != 'AgentTimeoutError'
                or trial['exception_info']['exception_message'] !=
                    'Agent execution timed out after 90.0 seconds'
                or not commands or any(c.strip() not in allowed for c in commands)):
            raise ValueError('Exact read-only 90-second installed-agent timeout proof required')
        result['preserved_installed_timeout'] = {
            'workflow_run': workflow_report['run_id'], 'native_run': report['run_id'],
            'old_deadline_seconds': 90, 'new_deadline_seconds': 600,
            'maximum_requests_unchanged': 8, 'prior_calls_preserved': True}
        result.pop('error_type', None)
        result.pop('error', None)

    if resume_after_installed:
        result = json.loads(target.read_text())
        installed = result.get('installed_agent', {})
        if (not result.get('steps') or result['steps'][-1] != {
                'action': 'run_agent', 'status': 'done'}
                or installed.get('agent_completion_confirmed') is not True
                or installed.get('version') != result.get('first_installation')):
            raise ValueError('A completed first installed-agent run is required')
        archive = folder / 'acceptance-after-installed-use.json'
        if archive.exists():
            raise ValueError('Post-installed observer continuation already used')
        result['post_installed_observer_continuation'] = {'paid_action_repeated': False}
        result.pop('error_type', None)
        result.pop('error', None)

    if resume_repair_native:
        result = json.loads(target.read_text())
        prior = result.get('repaired_review', {})
        incomplete = prior.get('incomplete_probe', {})
        if (result.get('unsafe_review', {}).get('decision') != 'blocked'
                or prior.get('error') != (
                    'Native probe incomplete; retained evidence requires review')
                or not 0 <= prior.get('verified_probes', -1) < 4
                or incomplete.get('model_requests') != 0
                or incomplete.get('native_run') is not None):
            raise ValueError('Exact unused repair-probe native failure required')
        archive = folder / ('acceptance-repair-native-' + prior['run_id'] + '.json')
        if archive.exists():
            raise ValueError('Repair native continuation already attempted')
        result.setdefault('preserved_repair_native_failures', []).append(prior)
        result.pop('error_type', None)
        result.pop('error', None)

    def save():
        target.write_text(json.dumps(result, indent=2) + '\n')

    with httpx.Client(base_url=origin, timeout=30, trust_env=False,
                      follow_redirects=False) as client:
        response = client.post('/api/login', headers={'Origin': origin,
            'X-SkillGuard-Origin': origin}, json={
            'code': (folder / 'access-code.txt').read_text().strip()})
        response.raise_for_status()

        def state():
            for attempt in range(10):
                try:
                    response = client.get('/api/state')
                    response.raise_for_status()
                    return response.json()
                except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as error:
                    if (isinstance(error, httpx.HTTPStatusError)
                            and error.response.status_code != 409):
                        raise
                    if attempt == 9:
                        raise
                    time.sleep(min(attempt + 1, 2))

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
            # Eight native preflight/live runs can each take up to 600 seconds.
            # This is observation only; the server owns execution and never retries it.
            deadline = time.monotonic() + 10800
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
            if not (resume_first_review or resume_validation or resume_model
                    or resume_completion_profile or resume_runner_start
                    or resume_installed_timeout or resume_after_installed
                    or resume_repair_native) and (
                    current['active'] or any(r['pending'] for r in current['reviews'])):
                raise ValueError('Public acceptance requires an empty dedicated workspace')
            if resume_repair_native:
                first = result['first_installation']
                review = pending(current)
                if not review['security'].get('can_resume'):
                    raise ValueError('Verified repair native recovery required')
                archive.write_bytes(target.read_bytes())
                current = action('resume_security', review_id=review['id'])
            elif resume_after_installed:
                job = current.get('job') or {}
                observing_unsafe = (result.get('running_action') == 'unsafe'
                    and job.get('action') == 'unsafe' and job.get('status') in {'running', 'done'})
                if (not current.get('active') or current['active']['id'] !=
                        result['first_installation'] or (not observing_unsafe
                            and any(r['pending'] for r in current['reviews']))):
                    raise ValueError('Installed source changed after the retained agent use')
                archive.write_bytes(target.read_bytes())
            elif resume_installed_timeout:
                if (not current.get('active') or current['active']['id'] !=
                        result['first_installation']
                        or any(r['pending'] for r in current['reviews'])):
                    raise ValueError('Installed source changed before deadline transition')
                archive.write_bytes(target.read_bytes())
                from skillguard.core import CoreWorkspace
                from skillguard.review.snapshot import digest

                workspace = CoreWorkspace(root, root / 'results/public-core')
                workspace.store._append(report['review_target']['review_id'],
                    'core_agent_deadline_transition', {
                        **result['preserved_installed_timeout'],
                        'failed_report_sha256': digest((native / 'report.json').read_bytes()),
                        'failed_trajectory_sha256': digest(trajectory_path.read_bytes()),
                        'reason': 'Prospective cloud wall-clock fix; no request/token cap '
                                  'or sandbox grant changes; original failed trial retained'})
            elif resume_runner_start:
                review = pending(current)
                if not review['security'].get('can_resume'):
                    raise ValueError('Source-bound zero-agent runner recovery unavailable')
                archive.write_bytes(target.read_bytes())
                current = action('resume_security', review_id=review['id'])
            elif resume_completion_profile:
                review = pending(current)
                if review['security'].get('can_change_completion_profile') is not True:
                    raise ValueError('Source-bound completion-profile transition unavailable')
                archive.write_bytes(target.read_bytes())
                current = action('review_security', review_id=review['id'])
            elif resume_model:
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
            if not (resume_validation or resume_model or resume_repair_native):
                if resume_after_installed:
                    first = result['first_installation']
                else:
                    if resume_installed_timeout:
                        first = result['first_installation']
                    else:
                        result['first_review'] = pending(current)['security']
                        save()
                        current = approve(current)
                        first = current['active']['id']
                    result['first_installation'] = first
                    current = action('run_agent', expected_active=first)
                    result['installed_agent'] = current['job']['result']
                current = action('unsafe', observe_only=observing_unsafe)
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
    group.add_argument('--resume-installed-timeout', action='store_true')
    group.add_argument('--resume-after-installed', action='store_true')
    group.add_argument('--resume-repair-native', action='store_true')
    group.add_argument('--resume-completion-profile', action='store_true')
    group.add_argument('--resume-runner-start', '--resume-zero-agent',
                       dest='resume_runner_start', action='store_true')
    parser.add_argument('--hosting-folder', type=Path)
    args = parser.parse_args()
    result = workflow(Path(__file__).resolve().parents[1],
                      resume_first_review=args.resume_first_review,
                      resume_validation=args.resume_validation, resume_model=args.resume_model,
                      resume_completion_profile=args.resume_completion_profile,
                      resume_runner_start=args.resume_runner_start,
                      resume_installed_timeout=args.resume_installed_timeout,
                      resume_after_installed=args.resume_after_installed,
                      resume_repair_native=args.resume_repair_native,
                      hosting_folder=args.hosting_folder)
    print(json.dumps({k: result[k] for k in ('passed', 'url', 'hosting_mode',
                                           'rollback_verified')}, indent=2))
