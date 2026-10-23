"""Candidate-bound orchestration of the existing native receipt agent trial."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from skillguard.evaluation.agent_task_protocol import CORE_PROTOCOLS, REPAIRED_PROTOCOL
from skillguard.models.bounded_transport import TEXT_RESERVATION
from skillguard.models.spending_policy import project_cap
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def review_test_digest(review: dict) -> str:
    return digest(json.dumps(review['latest'].get('core_test', {}), sort_keys=True).encode())


def parser_checks_valid(review: dict) -> bool:
    from scripts.core_openshell_environment import CORE_POLICY
    from skillguard.core import SCOPE

    test, static = review['latest'].get('core_test', {}), review['latest'].get('static', {})
    return (test.get('passed') is True and test.get('scope') == SCOPE
        and test.get('candidate_sha256') == review['candidate_sha256']
        and test.get('policy_sha256') == digest(CORE_POLICY.encode())
        and test.get('static_sha256') == digest(json.dumps(static, sort_keys=True).encode())
        and static.get('overall_status') == 'passed' and static.get('incomplete_scans') == []
        and 'core_rejection' not in review['latest'])


def has_disclosure(review: dict) -> bool:
    return any(e['data'].get('terminal_fake_canary_disclosure') is True
               for e in review.get('history', []))


def agent_checks_valid(review: dict) -> bool:
    agent = review['latest'].get('core_agent_test', {})
    return (parser_checks_valid(review) and not has_disclosure(review)
        and agent.get('agent_task_passed') is True
        and agent.get('candidate_sha256') == review['candidate_sha256']
        and agent.get('core_test_sha256') == review_test_digest(review)
        and agent.get('instruction_protocol') in CORE_PROTOCOLS)


def selected_candidate(root: Path, target: dict) -> dict:
    store = Path(target['store']).resolve()
    if not store.is_relative_to((root / 'results').resolve()):
        raise ValueError('Selected agent review store must be local to project results')
    review = ReviewStore(store).get(target['review_id'])
    if (not parser_checks_valid(review)
            or target.get('candidate_sha256') != review['candidate_sha256']
            or target.get('core_test_sha256') != review_test_digest(review)):
        raise ValueError('Selected agent candidate lacks current passing parser/static checks')
    candidate = Path(review['snapshot'])
    files = {p.relative_to(candidate).as_posix() for p in candidate.rglob('*') if p.is_file()}
    if files != {'SKILL.md', 'scripts/parse_receipt.py'}:
        raise ValueError('Agent trial requires exactly the selected guide and parser')
    parser_sha = digest((candidate / 'scripts/parse_receipt.py').read_bytes())
    if target.get('parser_sha256') != parser_sha:
        raise ValueError('Selected parser differs from proposal')
    if target.get('installed_version') is not None:
        from skillguard.core import CoreWorkspace

        workspace = CoreWorkspace(root, store.parent)
        if workspace.installed()['active'] != target['installed_version']:
            raise ValueError('Installed agent version changed before execution')
        manifest, installed = workspace.version(target['installed_version'])
        if (manifest['review_id'] != review['id']
                or manifest['candidate_sha256'] != review['candidate_sha256']
                or digest((installed / 'SKILL.md').read_bytes()) != digest(
                    (candidate / 'SKILL.md').read_bytes())):
            raise ValueError('Installed agent source differs from the selected review')
    return {**target, 'snapshot': str(candidate)}


def prepare_proposal(root: Path, store: Path, review: dict, *,
                     installed_version: str | None = None) -> Path:
    if has_disclosure(review):
        raise ValueError('Earlier prohibited disclosure remains blocking; review a new candidate')
    if not parser_checks_valid(review):
        raise ValueError('Run passing local receipt/static checks before the agent test')
    from skillguard.evaluation.receipt_template import template_path

    source = template_path(root)
    proposal = json.loads(source.read_text())
    candidate = Path(review['snapshot'])
    target = {'store': str(store.resolve()), 'review_id': review['id'],
        'candidate_sha256': review['candidate_sha256'],
        'core_test_sha256': review_test_digest(review),
        'parser_sha256': digest((candidate / 'scripts/parse_receipt.py').read_bytes())}
    if installed_version is not None:
        target['installed_version'] = installed_version
    selected_candidate(root, target)
    proposal.update(review_target=target, instruction_protocol=REPAIRED_PROTOCOL,
        execution_enabled=True, status='authorized_2026_10_22',
        aggregate_cap_usd=project_cap(root / 'results'),
        app_request_id=uuid.uuid4().hex,
        reservation_profile=TEXT_RESERVATION,
        scope='One native agent test of this reviewed candidate on the fixed fictional receipt',
        continuation_of='receipt-agent-72fc12e8',
        reviewed_files={str(candidate / name): digest((candidate / name).read_bytes())
                        for name in ('SKILL.md', 'scripts/parse_receipt.py')})
    path = root / 'results' / ('receipt-live-probe-core-' + uuid.uuid4().hex + '.json')
    path.write_text(json.dumps(proposal, indent=2) + '\n')
    return path


def run_test(root: Path, store: Path, review: dict, *, fresh: bool = False,
             installed_version: str | None = None) -> dict:
    from scripts.receipt_live_workflow import workflow

    if not fresh and agent_checks_valid(review):
        return review['latest']['core_agent_test']
    proposal = prepare_proposal(root, store, review, installed_version=installed_version)
    result = workflow(root, proposal)
    if result['status'] != 'verified' or not result.get('runner_stopped'):
        raise ValueError('Native agent trial did not finish; retained evidence needs review')
    return ReviewStore(store).get(review['id'])['latest']['core_agent_test']
