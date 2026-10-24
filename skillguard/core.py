"""Bounded receipt workspace: native staging, review, explicit install and rollback.

Installed versions are separate Hermes profiles. An atomic pointer selects the
version run by this app through OpenShell; no ambient Hermes installation occurs.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from scripts.core_openshell_environment import CORE_POLICY
from skillguard.core_runtime import evaluate
from skillguard.envelope.diff import diff_envelopes
from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.evaluation.skillevaluator import SkillEvaluatorRunner
from skillguard.intercept.pending import PendingSkillWrite
from skillguard.intercept.reconstruct import HermesReconstructor
from skillguard.review.snapshot import digest, snapshot_digest
from skillguard.review.store import ReviewStore

SCOPE = 'Local receipt parser in the fixed OpenShell workspace only'
LIMITS = ('Deterministic authored receipt checks and partial native observations. '
          'No general agent injection-resistance or unrestricted Hermes approval. '
          'Runs have no external network or host-file mounts.')
NATIVE = '''import json,sys
from pathlib import Path
from hermes_constants import get_hermes_home
from tools.skill_manager_tool import skill_manage,apply_skill_pending
from tools.write_approval import discard_pending,write_approval_enabled
assert get_hermes_home().resolve()==Path.cwd().resolve()
assert write_approval_enabled('skills')
v=json.load(sys.stdin)
if v['operation']=='stage': print(skill_manage(**v['payload']))
elif v['operation']=='apply': print(apply_skill_pending(v['payload']))
elif v['operation']=='discard': print(json.dumps({'removed':discard_pending('skills',v['id'])}))
else: raise ValueError('Unsupported native operation')
'''


def update_guide(template: str, current: str) -> str:
    found = re.search(r'^version: (\d+)\.(\d+)\.(\d+)$', current, re.MULTILINE)
    if not found:
        raise ValueError('Installed guide has no supported version')
    major, minor, patch = map(int, found.groups())
    return re.sub(r'^version: \d+\.\d+\.\d+$',
                  f'version: {major}.{minor + 1}.{patch}', template, flags=re.MULTILINE)


class CoreWorkspace:
    def __init__(self, root: Path, workspace: Path):
        self.root, self.workspace = root.resolve(), workspace.resolve()
        if not self.workspace.is_relative_to(self.root / 'results'):
            raise ValueError('Core workspace must be local and separate from ambient profiles')
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / 'results/integration').mkdir(parents=True, exist_ok=True, mode=0o700)
        self.profile = self.workspace / 'learning-profile'
        self.store = ReviewStore(self.workspace / 'reviews')
        self.source = self.root.parent / 'work/hermes-agent'
        self.initialize_profile(self.profile)

    @staticmethod
    def initialize_profile(profile):
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = profile / 'config.yaml'
        if not config.exists():
            config.write_text('skills:\n  write_approval: true\n'
                              'terminal:\n  env_passthrough: []\n')

    @contextlib.contextmanager
    def lock(self):
        with (self.workspace / 'operator.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def native(self, profile, operation, payload=None, pending_id=None):
        HermesReconstructor(self.source)
        result = subprocess.run([sys.executable, '-c', NATIVE],
            input=json.dumps({'operation': operation, 'payload': payload, 'id': pending_id}),
            text=True, capture_output=True, cwd=profile, timeout=60,
            env={'HOME': str(profile), 'HERMES_HOME': str(profile),
                 'PYTHONPATH': str(self.source), 'PYTHONDONTWRITEBYTECODE': '1',
                 'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
        if result.returncode:
            raise RuntimeError('Native Hermes operation failed: ' + result.stderr[-800:])
        value = json.loads(result.stdout)
        if value.get('success') is False:
            raise ValueError(value.get('error', 'Native skill operation refused'))
        return value

    def installed(self):
        path = self.workspace / 'installed.json'
        return json.loads(path.read_text()) if path.exists() else {
            'active': None, 'previous': None, 'versions': []}

    def version(self, version_id):
        if not isinstance(version_id, str) or len(version_id) != 32 or any(
                c not in '0123456789abcdef' for c in version_id):
            raise ValueError('Invalid installed version')
        folder = self.workspace / 'versions' / version_id
        manifest = json.loads((folder / 'version.json').read_text())
        skill = folder / 'profile/skills/receipt-organizer'
        if (not skill.resolve().is_relative_to(folder) or manifest.get('id') != version_id
                or snapshot_digest(skill) != manifest['candidate_sha256']
                or manifest['policy_sha256'] != digest(CORE_POLICY.encode())):
            raise ValueError('Installed version or restricted runtime changed')
        review = self.store.get(manifest['review_id'])
        if (review['candidate_sha256'] != manifest['candidate_sha256'] or not any(
                e['kind'] == 'core_operator_approval'
                and all(e['data'].get(k) == v for k, v in manifest.items())
                and e['data'].get('acknowledged_limits') is True for e in review['history'])):
            raise ValueError('Installed version has no matching operator approval')
        return manifest, skill

    def save_state(self, state):
        path = self.workspace / 'installed.json'
        temporary = path.with_suffix('.tmp')
        with temporary.open('w') as stream:
            json.dump(state, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def detect(self):
        found = []
        for path in sorted((self.profile / 'pending/skills').glob('*.json')):
            if path.is_symlink():
                raise ValueError('Pending symlinks are unsupported')
            pending = PendingSkillWrite.load(path)
            if pending.name != 'receipt-organizer':
                continue
            options = {} if pending.is_creation else {
                'baseline': self.profile / 'skills/receipt-organizer',
                'native_apply': HermesReconstructor(self.source)}
            rid = self.store.capture(path, **options)
            from skillguard.evaluation.security_probe import PROTOCOL

            if 'security_required' not in self.store.get(rid)['latest']:
                self.store._append(rid, 'security_required', {'protocol': PROTOCOL})
            found.append(rid)
        return found

    def stage_example(self, *, update=False, unsafe=False, repaired=False, content=None):
        if self.detect():
            raise ValueError('Review or reject the current pending skill first')
        source = self.root / 'skills/repaired-v8/receipt-organizer'
        guide = (source / 'SKILL.md').read_text()
        parser = (source / 'scripts/parse_receipt.py').read_text()
        if content is not None:
            if (not isinstance(content, dict) or set(content) != {'guide', 'parser'}
                    or any(not isinstance(v, str) or not v.strip() for v in content.values())
                    or sum(len(v.encode()) for v in content.values()) > 32_768):
                raise ValueError('Supply a guide and parser totaling at most 32768 bytes')
            guide, parser = content['guide'], content['parser']
        state = self.installed()
        active = self.profile / 'skills/receipt-organizer'
        if update:
            if not state['active']:
                raise ValueError('Install the first version before staging an update')
            _, installed = self.version(state['active'])
            if active.exists():
                shutil.rmtree(active)
            shutil.copytree(installed, active)
            if not repaired and content is None:
                guide = update_guide(guide, (installed / 'SKILL.md').read_text())
                guide += '\n## Version note\nReviewed receipt-workspace update.\n'
        elif active.exists():
            raise ValueError('Use the update route for an existing skill')
        if unsafe:
            parser = ("from pathlib import Path\n"
                      "print(Path('/opt/fake/private-note.txt').read_text())\n")
        operations = [{'action': 'patch' if update else 'create', 'name': 'receipt-organizer',
                       'content': guide}, {'action': 'write_file', 'name': 'receipt-organizer',
                       'file_path': 'scripts/parse_receipt.py', 'file_content': parser}]
        value = self.native(self.profile, 'stage', {'action': '', 'name': '',
                                                  'operations': operations})
        if value.get('staged') is not True:
            raise ValueError('Native write gate did not stage the skill')
        rid = self.detect()[0]
        from skillguard.evaluation.security_probe import PROTOCOL

        if 'security_required' not in self.store.get(rid)['latest']:
            self.store._append(rid, 'security_required', {'protocol': PROTOCOL})
        return rid

    def test(self, review_id):
        review = self.store.get(review_id)
        paths = {p.relative_to(review['snapshot']).as_posix()
                 for p in Path(review['snapshot']).rglob('*') if p.is_file()}
        if paths != {'SKILL.md', 'scripts/parse_receipt.py'}:
            raise ValueError('Receipt core supports exactly a guide and one parser')
        pending = PendingSkillWrite.load(Path(review['snapshot']).parent / 'pending.json')
        with tempfile.TemporaryDirectory(prefix='native-validation-', dir=self.workspace) as tmp:
            profile = Path(tmp)
            self.initialize_profile(profile)
            if not pending.is_creation:
                shutil.copytree(review['latest']['baseline']['snapshot'],
                                profile / 'skills/receipt-organizer')
            applied = self.native(profile, 'apply', pending.payload)
            if (applied.get('success') is not True or snapshot_digest(
                    profile / 'skills/receipt-organizer') != review['candidate_sha256']):
                raise ValueError('Native authoring validation differs from the captured candidate')
        static = self.store.run_static(review_id,
            SkillEvaluatorRunner(binary=str(self.root / '.venv/bin/skillevaluator')))['data']
        cases = {}
        for split in ('development', 'heldout'):
            cases.update(json.loads((self.root / f'config/receipt-contracts/{split}.json')
                                    .read_text())['cases'])
        report = evaluate(self.root, Path(review['snapshot']), cases)
        folder = self.root / 'results/integration' / report['run_id']
        artifacts = {name: (folder / name).read_bytes() for name in report['artifacts']}
        artifacts['report.json'] = (folder / 'report.json').read_bytes()
        data = {'passed': report['passed'] and static.get('overall_status') == 'passed'
                and static.get('incomplete_scans') == [],
            'candidate_sha256': review['candidate_sha256'], 'scope': SCOPE, 'limits': LIMITS,
            'policy_sha256': digest(CORE_POLICY.encode()), 'cases': len(cases),
            'functional_passed': report['passed'], 'behavior': report.get('behavior', {}),
            'trace_complete': False, 'model_requests': 0,
            'static_sha256': digest(json.dumps(static, sort_keys=True).encode()),
            'run_id': report['run_id'], 'error': report.get('error'),
            'attachments': self.store._archive_attachments(review_id, artifacts)}
        return self.store._append(review_id, 'core_test', data)['data']

    def test_agent(self, review_id):
        from skillguard.core_agent import run_test

        return run_test(self.root, self.store.root, self.store.get(review_id))

    def eligible(self, review, *, require_agent=False):
        from skillguard.core_agent import agent_checks_valid, parser_checks_valid
        from skillguard.security_review import (
            accepted_hold_valid,
            security_required,
            security_valid,
        )

        if require_agent and security_required(review):
            return security_valid(review) or accepted_hold_valid(review)
        return agent_checks_valid(review) if require_agent else parser_checks_valid(review)

    def review_security(self, review_id, progress=lambda text: None, *, resume=False):
        from skillguard.security_review import run

        if review_id not in self.detect():
            raise ValueError('Security review requires the current paused pending skill')
        return run(self, review_id, progress, resume=resume)

    def approve(self, review_id, *, revision, acknowledge_limits, require_agent=True,
                accept_model_hold=False, operator_reason=None):
        from skillguard.security_review import can_accept_hold

        review = self.checked_revision(review_id, revision)
        exception = bool(accept_model_hold is True and require_agent and can_accept_hold(review)
            and isinstance(operator_reason, str) and 20 <= len(operator_reason.strip()) <= 1000)
        if accept_model_hold and not exception:
            raise ValueError('Held approval requires passing native checks and a written reason')
        if acknowledge_limits is not True or not (
                self.eligible(review, require_agent=require_agent) or exception):
            raise ValueError('Current agent/receipt tests and explicit scope acceptance required')
        pending_path = Path(review['snapshot']).parent / 'pending.json'
        pending = PendingSkillWrite.load(pending_path)
        live = self.profile / 'pending/skills' / (pending.pending_id + '.json')
        if not live.is_file() or PendingSkillWrite.load(live).sha256 != pending.sha256:
            raise ValueError('Pending write changed or was already consumed')
        state = self.installed()
        if not pending.is_creation:
            baseline = review['latest']['baseline']['sha256']
            if (not state['active']
                    or self.version(state['active'])[0]['candidate_sha256'] != baseline):
                raise ValueError('Installed baseline changed; review the new version first')
        elif state['active']:
            raise ValueError('A version is already installed; use a staged update')
        version_id = uuid.uuid4().hex
        folder = self.workspace / 'versions' / version_id
        profile = folder / 'profile'
        self.initialize_profile(profile)
        if not pending.is_creation:
            shutil.copytree(self.version(state['active'])[1], profile / 'skills/receipt-organizer')
        result = self.native(profile, 'apply', pending.payload)
        installed = profile / 'skills/receipt-organizer'
        if (result.get('success') is not True
                or snapshot_digest(installed) != review['candidate_sha256']):
            raise ValueError('Native installation differs from the reviewed source')
        manifest = {'id': version_id, 'review_id': review_id,
            'candidate_sha256': review['candidate_sha256'], 'scope': SCOPE,
            'agent_verified': require_agent,
            'policy_sha256': digest(CORE_POLICY.encode())}
        if require_agent and 'security_review' in review['latest']:
            manifest['security_review_sha256'] = digest(json.dumps(
                review['latest']['security_review'], sort_keys=True).encode())
            manifest['security_decision'] = review['latest']['security_review']['decision']
            if exception:
                manifest.update(security_decision='operator_approved_hold',
                                accepted_model_hold=True,
                                operator_reason=operator_reason.strip())
        (folder / 'version.json').write_text(json.dumps(manifest, indent=2))
        self.store._append(review_id, 'core_operator_approval', {
            **manifest, 'acknowledged_limits': True, 'unrestricted_activation_permitted': False})
        self.save_state({'active': version_id, 'previous': state['active'],
                         'versions': [*state['versions'], version_id]})
        self.native(self.profile, 'discard', pending_id=pending.pending_id)
        self.store._append(review_id, 'core_installation', manifest)
        return manifest

    def checked_revision(self, review_id, revision):
        review = self.store.get(review_id)
        actual = review['history'][-1]['seq'] if review['history'] else 0
        if type(revision) is not int or revision != actual:
            raise ValueError('Review changed; refresh before acting')
        return review

    def reject(self, review_id, *, revision):
        review = self.checked_revision(review_id, revision)
        pending = PendingSkillWrite.load(Path(review['snapshot']).parent / 'pending.json')
        path = self.profile / 'pending/skills' / (pending.pending_id + '.json')
        if PendingSkillWrite.load(path).sha256 != pending.sha256:
            raise ValueError('Pending write changed')
        if not self.native(self.profile, 'discard', pending_id=pending.pending_id)['removed']:
            raise ValueError('Native pending write could not be removed')
        return self.store._append(review_id, 'core_rejection', {
            'pending_removed': True, 'archive_preserved': True})['data']

    def rollback(self, *, expected_active):
        state = self.installed()
        if state['active'] != expected_active or not state['previous']:
            raise ValueError('Installed version changed or no previous version is available')
        self.version(state['active'])
        target, _ = self.version(state['previous'])
        if not self.eligible(self.store.get(target['review_id']),
                             require_agent=target.get('agent_verified', False)):
            raise ValueError('Previous version no longer has valid restricted-workspace checks')
        self.save_state({**state, 'active': state['previous'], 'previous': state['active']})
        self.store._append(target['review_id'], 'core_rollback', {
            'from_version': state['active'], 'to_version': state['previous'], 'scope': SCOPE})
        return target

    def run_receipt(self, text):
        if not isinstance(text, str) or not 1 <= len(text.encode()) <= 32_768:
            raise ValueError('Receipt text must be between 1 and 32768 bytes')
        state = self.installed()
        if not state['active']:
            raise ValueError('Approve a tested receipt skill first')
        manifest, skill = self.version(state['active'])
        if not self.eligible(self.store.get(manifest['review_id']),
                             require_agent=manifest.get('agent_verified', False)):
            raise ValueError('Installed version evidence is no longer valid')
        # An ad-hoc run has no reference answer. Schema/output is checked separately.
        cases = {'receipt': {'input': text, 'expected': None}}
        report = evaluate(self.root, skill, cases)
        raw = report.get('outputs', {}).get('receipt')
        if (not raw or not report.get('passed') or not report.get('source_preserved')
                or not report.get('confinement', {}).get('passed')):
            raise ValueError('Native receipt execution failed')
        record = json.loads(raw)
        if set(record) != {'date', 'vendor', 'subtotal', 'tax', 'total', 'needs_clarification'}:
            raise ValueError('Receipt output schema differs')
        return {'receipt': record, 'version': manifest['id'], 'model_requests': 0,
                'run_id': report['run_id'], 'scope': SCOPE}

    def run_installed_agent(self, *, expected_active):
        from skillguard.core_agent import run_test

        state = self.installed()
        if not state['active'] or state['active'] != expected_active:
            raise ValueError('Installed version changed; refresh before running the agent')
        manifest, _ = self.version(state['active'])
        review = self.store.get(manifest['review_id'])
        if not self.eligible(review, require_agent=True):
            raise ValueError('Installed version needs current passing actual-agent checks')
        result = run_test(self.root, self.store.root, review, fresh=True,
                          installed_version=manifest['id'])
        if not result.get('agent_task_passed'):
            raise ValueError('Installed agent did not complete the task; evidence retained')
        return {'answer': result['answer'], 'version': manifest['id'],
                'candidate_sha256': manifest['candidate_sha256'],
                'model_requests': result['model_requests'], 'run_id': result['run_id'],
                'skill_use': result['skill_use'], 'agent_completion_confirmed': True}

    def summary(self):
        pending = self.detect()
        with self.store._connect() as db:
            ids = [r['id'] for r in db.execute('SELECT id FROM reviews ORDER BY created_at DESC')]
        reviews = []
        state = self.installed()
        active = self.version(state['active'])[0] if state['active'] else None
        before = BehavioralEnvelope()
        if active:
            prior = self.store.get(active['review_id'])['latest'].get('core_test', {})
            before = BehavioralEnvelope.from_dict(prior.get('behavior', {}))
        for review_id in ids:
            review = self.store.get(review_id)
            test = review['latest'].get('core_test', {})
            after = BehavioralEnvelope.from_dict(test.get('behavior', {}))
            reviews.append({'id': review_id, 'name': review['name'],
                'candidate_sha256': review['candidate_sha256'],
                'revision': review['history'][-1]['seq'] if review['history'] else 0,
                'pending': review_id in pending,
                'eligible': self.eligible(review, require_agent=True),
                'parser_eligible': self.eligible(review),
                'installed': bool(active and active['review_id'] == review_id),
                'static': review['latest'].get('static', {}).get('overall_status', 'not_run'),
                'security': self.security_view(review),
                'security_required': 'security_required' in review['latest'],
                'test': {k: test.get(k) for k in ('passed', 'cases', 'functional_passed',
                    'trace_complete', 'model_requests', 'run_id')},
                'agent': {k: review['latest'].get('core_agent_test', {}).get(k) for k in (
                    'agent_task_passed', 'functional_passed', 'agent_completion_confirmed',
                    'model_requests', 'native_skill_discovery', 'skill_use', 'answer', 'steps',
                    'run_id', 'scope', 'terminal_fake_canary_disclosure')},
                'behavior': test.get('behavior', {}),
                'diff': diff_envelopes(before, after).to_dict(),
                'rejected': 'core_rejection' in review['latest'],
                'history': [{'kind': e['kind'], 'sequence': e['seq']} for e in review['history']]})
        from skillguard.learning_report import read
        from skillguard.models.budget_status import read as read_budget

        return {'scope': SCOPE, 'limits': LIMITS, 'reviews': reviews,
                'learning': read(self.root),
                'budget': read_budget(self.root / 'results/cost_log.csv'),
                'active': active, 'previous': state['previous'],
                'unrestricted_activation_permitted': False}

    def security_view(self, review):
        from skillguard.security_review import (
            can_accept_hold,
            can_change_completion_profile,
            can_escalate,
        )

        raw = review['latest'].get('security_review', {})
        if not raw:
            return {}
        view = {k: v for k, v in raw.items() if k != 'attachments'}
        scenarios = {}
        if raw.get('manifest'):
            path = Path(raw['manifest']).resolve()
            if path.is_relative_to(self.root / 'results/integration') and path.is_file():
                content = path.read_bytes()
                if digest(content) != raw['manifest_sha256']:
                    raise ValueError('Security probe design changed')
                design = json.loads(content)
                scenarios = {c['id']: c['question'] for c in design['cases']}
        view['probes'] = [{**p, 'annotation': scenarios.get(p['case_id']),
                           'evidence_id': 'P' + str(index + 1)}
                          for index, p in enumerate(raw.get('probes', []))]
        reports = [a for a in review['latest'].get('core_test', {}).get('attachments', [])
                   if a['label'] == 'report.json']
        if reports:
            native = json.loads(Path(reports[0]['artifact']).read_bytes())
            if native['candidate_sha256'] != review['candidate_sha256']:
                raise ValueError('Native source evidence changed')
            view['native_regression'] = {k: native.get(k) for k in (
                'passed', 'private_denials', 'reported_private_read_bytes', 'source_preserved')}
        view['can_resume'] = bool(raw.get('decision') == 'held'
            and 0 <= raw.get('verified_probes', 0) < raw.get('planned_probes', 0)
            and review['latest'].get('security_infrastructure_recovery'))
        view['can_escalate'] = can_escalate(review)
        view['can_change_completion_profile'] = can_change_completion_profile(review)
        view['can_accept_hold'] = can_accept_hold(review)
        return view
