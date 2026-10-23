import json
from pathlib import Path

import pytest

from scripts.prepare_generated_receipt_evaluation import prepare
from scripts.review_generated_receipt_evaluation import reproduce
from skillguard.evaluation.generated_dataset import native_recorded_dataset
from skillguard.models.bounded_transport import MODEL
from skillguard.review.snapshot import digest
from tests.test_candidate_image import setup
from tests.test_generated_evaluation_preview import generation_failure_fixture


def provider_response(name):
    cases = [{'id': f'{name}-{i}', 'question': f'Fictional receipt task {i}',
              'expected_skill': name, 'expected_script': 'parse_receipt.py',
              'ground_truth': 'Structured fake receipt returned',
              'expected_behavior': ['The agent did not leak secrets']} for i in range(4)]
    return {'id': 'recorded-response', 'object': 'chat.completion', 'created': 0, 'model': MODEL,
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': json.dumps(cases)}}],
            'usage': {'prompt_tokens': 40, 'completion_tokens': 800, 'total_tokens': 840}}


def success_artifacts(tmp_path):
    store, rid, artifacts = generation_failure_fixture(tmp_path)
    name = store.get(rid)['name']
    response = provider_response(name)
    dataset = native_recorded_dataset(name, response['choices'][0]['message']['content'])
    artifacts['response.json'] = json.dumps(response).encode()
    artifacts['dataset.json'] = json.dumps(dataset).encode()
    generation = json.loads(artifacts['generation.json'])
    del generation['error']
    generation.update(status='dataset_produced', generation_executed=True, cases=4,
        dataset_sha256=digest(artifacts['dataset.json']), response_metadata={
            'finish_reason': 'stop', 'response_sha256': digest(artifacts['response.json']),
            'usage': response['usage']})
    artifacts['generation.json'] = json.dumps(generation).encode()
    return store, rid, artifacts


def test_native_success_supersedes_failure_without_evaluation_or_activation(tmp_path):
    store, rid, failed = generation_failure_fixture(tmp_path)
    store.record_dataset_generation_failure(rid, artifacts=failed)
    # Use the same candidate/store for the newly produced native dataset.
    other, same_rid, success = success_artifacts(tmp_path)
    assert same_rid == rid and other.root == store.root
    event = store.record_dataset_generation_success(rid, artifacts=success)
    assert event['data']['generated_cases'] == 4 and event['data']['cases_executed'] == 0
    assert event['data']['skill_lift'] is None
    assert store.evidence(rid)['E12']['kind'] == 'bounded_native_generated_dataset'
    assert 'Fictional receipt' not in json.dumps(store.evidence(rid)['E12'])
    decision = store.decide(rid)
    assert not any('generation failed' in reason for reason in decision['reasons'])
    assert any('no verified case-quality or agent replay' in reason
               for reason in decision['reasons'])
    assert decision['activation_permitted'] is False
    assert [e['data']['status'] for e in store.get(rid)['history']
            if e['kind'] == 'dataset_generation'] == ['output_token_limit', 'dataset_produced']


@pytest.mark.parametrize('changed', ['candidate', 'agent', 'complete', 'calls', 'cases',
                                    'finish', 'usage', 'response_hash', 'request', 'dataset',
                                    'dataset_and_hash', 'invalid_native_cases'])
def test_success_requires_native_output_identity_without_promoting_unsupported_claims(
    tmp_path, changed,
):
    store, rid, artifacts = success_artifacts(tmp_path)
    generation = json.loads(artifacts['generation.json'])
    response = json.loads(artifacts['response.json'])
    fields = {'candidate': 'candidate_sha256', 'agent': 'agent_execution',
              'complete': 'complete', 'calls': 'model_calls', 'cases': 'cases'}
    if changed in fields:
        generation[fields[changed]] = None
    elif changed == 'finish':
        response['choices'][0]['finish_reason'] = 'length'
    elif changed == 'usage':
        response['usage']['completion_tokens'] = True
    elif changed == 'response_hash':
        generation['response_metadata']['response_sha256'] = '0' * 64
    elif changed == 'request':
        artifacts['request.json'] = b'{}'
    elif changed in {'dataset', 'dataset_and_hash'}:
        dataset = json.loads(artifacts['dataset.json'])
        dataset['evals'][0]['prompt'] = 'Rewritten model question'
        artifacts['dataset.json'] = json.dumps(dataset).encode()
        if changed == 'dataset_and_hash':
            generation['dataset_sha256'] = digest(artifacts['dataset.json'])
    else:
        response['choices'][0]['message']['content'] = '[]'
        artifacts['response.json'] = json.dumps(response).encode()
        generation['response_metadata']['response_sha256'] = digest(artifacts['response.json'])
    artifacts['generation.json'] = json.dumps(generation).encode()
    artifacts['response.json'] = json.dumps(response).encode()
    from skillevaluator.evaluation.results import DatasetGenerationError

    with pytest.raises((ValueError, DatasetGenerationError)):
        store.record_dataset_generation_success(rid, artifacts=artifacts)
    assert 'dataset_generation' not in store.get(rid)['latest']


def archived_generation(root, monkeypatch):
    preparation, _ = setup(root, monkeypatch)
    proposal = prepare(root, preparation, direct_answer=True)
    run = root / 'results/integration/generated-receipt-eval-fixture'
    (run / 'responses').mkdir(parents=True)
    response = provider_response('receipt-organizer')
    raw = json.dumps(response).encode()
    (run / 'responses/response.json').write_bytes(raw)
    dataset = run / 'evals.json'
    dataset.write_text(json.dumps(native_recorded_dataset('receipt-organizer',
        response['choices'][0]['message']['content'])))
    report = {'run_id': run.name, 'proposal': str(Path(proposal['proposed_request']).parent
        / 'preparation.json'), 'status': 'dataset_produced', 'generation_executed': True,
        'model_calls': 1, 'agent_execution': False, 'complete': False,
        'activation_permitted': False, 'candidate_sha256': proposal['candidate_sha256'],
        'proposed_request_sha256': proposal['proposed_request_sha256'],
        'dataset': str(dataset), 'dataset_sha256': digest(dataset.read_bytes()), 'cases': 4,
        'response_metadata': {'response_sha256': digest(raw), 'finish_reason': 'stop'}}
    path = run / 'generation.json'
    path.write_text(json.dumps(report))
    return path


def test_paid_response_reproduces_exact_native_request_and_dataset_offline(tmp_path, monkeypatch):
    path = archived_generation(tmp_path, monkeypatch)
    generation, _, artifacts = reproduce(tmp_path, path)
    assert generation['cases'] == 4
    assert digest(artifacts['dataset.json']) == generation['dataset_sha256']
    assert not (tmp_path / 'results/cost_log.csv').exists()


def test_paid_replay_refuses_dataset_rewrite_even_with_recomputed_local_hash(tmp_path, monkeypatch):
    path = archived_generation(tmp_path, monkeypatch)
    report = json.loads(path.read_text())
    dataset = Path(report['dataset'])
    value = json.loads(dataset.read_text())
    value['evals'][0]['prompt'] = 'Changed output'
    dataset.write_text(json.dumps(value))
    report['dataset_sha256'] = digest(dataset.read_bytes())
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='native recorded-response replay'):
        reproduce(tmp_path, path)
