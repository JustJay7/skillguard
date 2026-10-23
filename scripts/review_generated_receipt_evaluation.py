"""Verify paid output with the native generator, then stage native starter tasks.

Only offline response replay and metadata scaffolding. No agent execution,
new inference, replacement generator/grader, resistance score or Skill Lift.
Native starter tasks require domain fixtures/grading before meaningful runs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

from scripts.generate_receipt_evaluation import validate_proposal
from scripts.prepare_generated_receipt_evaluation import native_generation_options
from skillguard.review.snapshot import artifact_tree_digest, digest


def reproduce(root: Path, generation_path: Path) -> tuple[dict, dict, dict[str, bytes]]:
    """Re-run native parsing against the exact archived response without network."""
    from skillevaluator.inference.client import LLMClient
    from skillevaluator.tier3.generate_dataset import (
        _generate_with_llm,
        _parse_skill,
        _to_agentskills_dataset,
    )

    generation_path = generation_path.resolve()
    if not generation_path.is_relative_to(root / 'results/integration'):
        raise ValueError('Generation must be an archived local result')
    generation = json.loads(generation_path.read_text())
    proposal_path = Path(generation['proposal'])
    proposal, expected_request = validate_proposal(root, proposal_path)
    if (generation.get('status') != 'dataset_produced'
            or generation.get('generation_executed') is not True
            or type(generation.get('model_calls')) is not int or generation['model_calls'] != 1
            or generation.get('agent_execution') is not False
            or generation.get('complete') is not False
            or generation.get('activation_permitted') is not False
            or generation.get('candidate_sha256') != proposal['candidate_sha256']
            or generation.get('proposed_request_sha256') != proposal['proposed_request_sha256']):
        raise ValueError('Native generation identity/scope differs')
    dataset = Path(generation['dataset']).resolve()
    responses = list((generation_path.parent / 'responses').glob('*.json'))
    if (dataset.parent != generation_path.parent or len(responses) != 1
            or digest(dataset.read_bytes()) != generation['dataset_sha256']):
        raise ValueError('Native generation artifacts changed')
    raw_response = responses[0].read_bytes()
    response = json.loads(raw_response)
    metadata = generation['response_metadata']
    if (digest(raw_response) != metadata['response_sha256']
            or len(response.get('choices', [])) != 1
            or response['choices'][0].get('finish_reason') != 'stop'
            or metadata.get('finish_reason') != 'stop'):
        raise ValueError('Native response is changed or incomplete')
    captured = []

    def offline_response(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        if payload != expected_request:
            raise ValueError('Native offline replay changed the reviewed request')
        captured.append(payload)
        return httpx.Response(200, json=response)

    environment = {
        'SKILL_EVAL_LLM_PROVIDER': 'openai-compatible',
        'SKILL_EVAL_LLM_MODEL': proposal['model'],
        'SKILL_EVAL_LLM_BASE_URL': 'https://api.tokenfactory.nebius.com/v1',
        'SKILL_EVAL_LLM_API_KEY': 'offline-recorded-response-not-a-credential'}
    with (
        httpx.Client(transport=httpx.MockTransport(offline_response), trust_env=False) as client,
        OpenAI(api_key=environment['SKILL_EVAL_LLM_API_KEY'],
               base_url=environment['SKILL_EVAL_LLM_BASE_URL'], max_retries=0,
               http_client=client) as sdk,
        patch.dict(os.environ, environment),
        patch.object(LLMClient, '_get_client', return_value=sdk),
        native_generation_options(sdk, direct_answer=proposal.get('direct_answer', False)),
    ):
        skill = _parse_skill(Path(proposal['skill']))
        cases = asyncio.run(_generate_with_llm(skill, full=True, fallback_to_template=False,
                                              announce_provider=False))
    if (len(captured) != 1 or generation.get('cases') != len(cases)
            or json.loads(dataset.read_text()) != _to_agentskills_dataset(skill['name'], cases)):
        raise ValueError('Dataset differs from native recorded-response replay')
    artifacts = {'generation.json': generation_path.read_bytes(),
        'proposal.json': proposal_path.read_bytes(),
        'request.json': Path(proposal['proposed_request']).read_bytes(),
        'response.json': raw_response, 'dataset.json': dataset.read_bytes()}
    return generation, proposal, artifacts


def review(root: Path, generation_path: Path) -> dict:
    from harbor.models.task.task import Task
    from skillevaluator.tier3.dataset_utils import load_dataset_entries

    generation, proposal, artifacts = reproduce(root, generation_path)
    folder = root / 'results/integration' / f'generated-case-review-{uuid.uuid4().hex[:8]}'
    folder.mkdir(mode=0o700)
    skill = folder / 'receipt-organizer'
    shutil.copytree(Path(proposal['skill']), skill)
    shutil.copyfile(Path(generation['dataset']), skill / 'evals/evals.json')
    entries = load_dataset_entries(skill / 'evals/evals.json')
    tasks, commands = [], []
    binary = str(root / '.venv/bin/skillevaluator')
    for index, entry in enumerate(entries):
        command = [binary, 'init-harbor-task', str(skill), '--case-id', entry['id'],
                   '--with-config']
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        (folder / f'scaffold-{index}.txt').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Native starter task scaffolding failed; logs retained')
        task = skill / 'evals/harbor' / entry['id']
        Task(task)  # Validate the actual Harbor schema, not just file presence.
        tasks.append({'case_id': entry['id'], 'task': str(task),
                      'task_sha256': artifact_tree_digest(task)})
        commands.append(command)
    command = [binary, 'tier3', 'validate', str(skill), '--harbor-contract', '--strict', '--json']
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    (folder / 'validation.json').write_text(result.stdout)
    (folder / 'validation-stderr.txt').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError('Native task contract validation failed; logs retained')
    report = {'run_id': folder.name, 'generation_run_id': generation['run_id'],
        'candidate_sha256': generation['candidate_sha256'],
        'dataset_sha256': generation['dataset_sha256'], 'generated_cases': len(entries),
        'native_response_reproduced': True, 'native_task_contract_valid': True,
        'tasks': tasks, 'validation': json.loads(result.stdout), 'commands': commands + [command],
        'model_calls': 0, 'agent_execution': False, 'cases_executed': 0,
        'complete': False, 'activation_permitted': False, 'skill_lift': None,
        'scope': 'Native generated dataset and starter-task validation; no execution',
        'limitations': ['Native starter instructions/grader are not a receipt domain oracle',
                        'Generated questions require live agent routing and receipt extraction',
                        'No measured adversarial resistance or Skill Lift']}
    (folder / 'review.json').write_text(json.dumps(report, indent=2) + '\n')
    # Original paid output and candidate context must stay unchanged after staging.
    reproduce(root, generation_path)
    from skillguard.review.store import ReviewStore

    parent = json.loads(Path(proposal['preparation']).read_text())
    store = ReviewStore(Path(parent['store']))
    event = store.record_dataset_generation_success(parent['review_id'], artifacts=artifacts)
    report['stored_generation'] = event['data']
    report['decision'] = store.decide(parent['review_id'])
    (folder / 'review.json').write_text(json.dumps(report, indent=2) + '\n')
    (root / 'results/generated-case-review-latest.json').write_text(
        json.dumps(report, indent=2) + '\n')
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--generation', type=Path, required=True)
    args = parser.parse_args()
    report = review(Path(__file__).resolve().parents[1], args.generation)
    print(json.dumps({k:report[k] for k in ('run_id', 'generated_cases',
        'native_response_reproduced', 'native_task_contract_valid', 'cases_executed', 'decision')},
        indent=2))


if __name__ == '__main__':
    main()
