import json
from pathlib import Path

import httpx
import pytest

from scripts.generate_receipt_evaluation import (
    ReviewedGenerationTransport,
    claim_proposal,
    response_metadata,
    validate_proposal,
)
from scripts.prepare_generated_receipt_evaluation import prepare
from skillguard.models.bounded_transport import MODEL, AgentCallBudget
from tests.test_candidate_image import setup


def test_native_generation_preview_exports_guide_and_guidance_without_source_or_secrets(
    tmp_path, monkeypatch,
):
    preparation, candidate = setup(tmp_path, monkeypatch)
    report = prepare(tmp_path, preparation)
    payload = json.loads(Path(report["proposed_request"]).read_text())
    serialized = json.dumps(payload)
    assert "known guide fixture" in serialized
    assert "misleading instructions" in serialized
    assert "print('fixture')" not in serialized
    assert "offline-preview-not-a-credential" not in serialized
    assert payload["max_tokens"] == 2000
    assert report["model_calls"] == 0
    assert report["generation_executed"] is False
    assert report["activation_permitted"] is False
    assert not (candidate / "evals").exists()


def proposal_fixture(tmp_path, monkeypatch):
    preparation, _ = setup(tmp_path, monkeypatch)
    report = prepare(tmp_path, preparation)
    proposal = Path(report["proposed_request"]).parent / "preparation.json"
    return report, proposal


def test_exact_native_export_and_candidate_context_are_rechecked(tmp_path, monkeypatch):
    report, path = proposal_fixture(tmp_path, monkeypatch)
    proposal, payload = validate_proposal(tmp_path, path)
    assert proposal == report
    assert payload["model"] == MODEL


@pytest.mark.parametrize("target", ["proposed-request.json", "receipt-organizer/SKILL.md",
                                     "receipt-organizer/evals/EVAL.md"])
def test_changed_export_or_context_is_refused_before_network(tmp_path, monkeypatch, target):
    _, path = proposal_fixture(tmp_path, monkeypatch)
    changed = path.parent / target
    changed.chmod(0o600)
    changed.write_text("changed")
    with pytest.raises(ValueError, match="changed|differs"):
        validate_proposal(tmp_path, path)


def test_transport_refuses_extra_exports_and_second_call_before_forwarding(tmp_path):
    budget = AgentCallBudget(tmp_path / "cost.csv", tmp_path / "responses", max_calls=1,
                             total_limit_usd=0.75)
    payload = {"model": MODEL, "max_tokens": 2000,
               "messages": [{"role": "user", "content": "reviewed fixture"}]}
    forwarded = []

    def upstream(request):
        forwarded.append(request)
        return httpx.Response(200, json={"usage": {"prompt_tokens": 40, "completion_tokens": 60}})

    transport = ReviewedGenerationTransport(budget, payload, httpx.MockTransport(upstream))
    url = "https://api.tokenfactory.nebius.com/v1/chat/completions"
    altered = payload | {"messages": [{"role": "user", "content": "unreviewed data"}]}
    with pytest.raises(ValueError, match="differs"):
        transport.handle_request(httpx.Request("POST", url, json=altered))
    assert forwarded == [] and budget.calls == 0
    transport.handle_request(httpx.Request("POST", url, json=payload))
    assert budget.calls == 1
    with pytest.raises(ValueError, match="request limit"):
        transport.handle_request(httpx.Request("POST", url, json=payload))
    assert len(forwarded) == 1


def test_one_call_claim_survives_a_new_invocation_and_duplicate_preview(tmp_path):
    proposal = {'proposed_request_sha256': 'a' * 64, 'candidate_sha256': 'b' * 64}
    claim = claim_proposal(tmp_path, proposal, tmp_path / 'first-run')
    assert json.loads(claim.read_text())['maximum_calls'] == 1
    with pytest.raises(ValueError, match='already claimed'):
        claim_proposal(tmp_path, proposal, tmp_path / 'second-run')


def test_historical_paid_generation_consumes_the_exact_request(tmp_path):
    run = tmp_path / 'results/integration/generated-receipt-eval-existing'
    run.mkdir(parents=True)
    proposal = {'proposed_request_sha256': 'a' * 64, 'candidate_sha256': 'b' * 64}
    (run / 'generation.json').write_text(json.dumps({
        'proposed_request_sha256': 'a' * 64, 'model_calls': 1,
        'generation_executed': False, 'error': 'truncated response'}))
    with pytest.raises(ValueError, match='already consumed'):
        claim_proposal(tmp_path, proposal, tmp_path / 'second-run')


def test_generation_claim_is_atomic_for_concurrent_invocations(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    proposal = {'proposed_request_sha256': 'a' * 64, 'candidate_sha256': 'b' * 64}

    def attempt(index):
        try:
            claim_proposal(tmp_path, proposal, tmp_path / str(index))
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, [1, 2])) == [False, True]


def test_native_direct_answer_preview_preserves_text_and_cost_limit(tmp_path, monkeypatch):
    preparation, _ = setup(tmp_path, monkeypatch)
    original = prepare(tmp_path, preparation)
    revised = prepare(tmp_path, preparation, direct_answer=True)
    a = json.loads(Path(original['proposed_request']).read_text())
    b = json.loads(Path(revised['proposed_request']).read_text())
    assert b == a | {'chat_template_kwargs': {'enable_thinking': False}}
    assert revised['model_calls'] == 0 and revised['requested_max_output_tokens'] == 2000
    path = Path(revised['proposed_request']).parent / 'preparation.json'
    assert validate_proposal(tmp_path, path)[1] == b


def test_truncated_provider_reply_is_explicit_and_preserves_usage(tmp_path):
    responses = tmp_path / 'responses'
    responses.mkdir()
    reply = {'choices': [{'finish_reason': 'length', 'message': {'content': 'not valid JSON'}}],
             'usage': {'prompt_tokens': 958, 'completion_tokens': 2000,
                       'completion_tokens_details': {'reasoning_tokens': 2000}}}
    raw = json.dumps(reply).encode()
    (responses / 'call.json').write_bytes(raw)
    metadata = response_metadata(responses)
    assert metadata['finish_reason'] == 'length'
    assert metadata['failure_kind'] == 'output_token_limit'
    assert metadata['usage'] == reply['usage']
    assert 'not valid JSON' not in json.dumps(metadata)
    from skillguard.review.snapshot import digest

    assert metadata['response_sha256'] == digest(raw)


def test_truncated_reply_cannot_be_accepted_even_if_visible_json_is_parseable(tmp_path):
    import csv

    budget = AgentCallBudget(tmp_path / 'cost.csv', tmp_path / 'responses', max_calls=1,
                             total_limit_usd=0.75)
    payload = {'model': MODEL, 'max_tokens': 2000,
               'messages': [{'role': 'user', 'content': 'reviewed fixture'}]}
    response = {'choices': [{'finish_reason': 'length', 'message': {'content': '[]'}}],
                'usage': {'prompt_tokens': 40, 'completion_tokens': 2000}}
    transport = ReviewedGenerationTransport(budget, payload,
        httpx.MockTransport(lambda request:httpx.Response(200, json=response)))
    with pytest.raises(ValueError, match='output-token limit'):
        transport.handle_request(httpx.Request('POST',
            'https://api.tokenfactory.nebius.com/v1/chat/completions', json=payload))
    assert budget.calls == 1
    assert response_metadata(tmp_path / 'responses')['finish_reason'] == 'length'
    row = list(csv.DictReader((tmp_path / 'cost.csv').open()))[0]
    assert row['status'] == 'completed' and float(row['estimated_cost_usd']) > 0


def generation_failure_fixture(tmp_path):
    from tests.test_policy_evidence import review

    store, rid, _ = review(tmp_path)
    candidate = store.get(rid)['candidate_sha256']
    payload = {'model': MODEL, 'max_tokens': 2000,
               'messages': [{'role': 'user', 'content': 'fictional guide only'}]}
    raw_request = json.dumps(payload).encode()
    from skillguard.review.snapshot import digest

    identity = digest(raw_request)
    proposal = {'candidate_sha256': candidate, 'proposed_request_sha256': identity,
                'maximum_calls': 1, 'requested_max_output_tokens': 2000,
                'aggregate_budget_cap_usd': 0.75}
    generation = {'scope': 'Native generated questions; no measured resistance or Skill Lift',
        'candidate_sha256': candidate, 'model': MODEL, 'model_calls': 1,
        'proposed_request_sha256': identity, 'generation_executed': False,
        'agent_execution': False, 'activation_permitted': False, 'complete': False,
        'error': 'Native generator could not parse dataset'}
    response = {'choices': [{'finish_reason': 'length',
                            'message': {'content': 'incomplete reply'}}],
                'usage': {'prompt_tokens': 958, 'completion_tokens': 2000}}
    artifacts = {'generation.json': json.dumps(generation).encode(),
        'proposal.json': json.dumps(proposal).encode(), 'request.json': raw_request,
        'response.json': json.dumps(response).encode()}
    return store, rid, artifacts


def test_paid_native_generation_failure_is_persistent_without_evaluation_credit(tmp_path):
    store, rid, artifacts = generation_failure_fixture(tmp_path)
    event = store.record_dataset_generation_failure(rid, artifacts=artifacts)
    assert event['data']['status'] == 'output_token_limit'
    assert event['data']['generated_cases'] == 0
    assert event['data']['usage']['completion_tokens'] == 2000
    assert 'incomplete reply' not in json.dumps(store.evidence(rid)['E12'])
    assert any('generation failed' in reason for reason in store.decide(rid)['reasons'])
    assert store.decide(rid)['activation_permitted'] is False


@pytest.mark.parametrize('changed', ['candidate', 'scope', 'success', 'agent', 'complete',
                                    'calls', 'finish', 'tokens', 'request', 'proposal'])
def test_inconsistent_native_generation_failure_is_refused(tmp_path, changed):
    store, rid, artifacts = generation_failure_fixture(tmp_path)
    filename = ('response.json' if changed in {'finish', 'tokens'} else
                'request.json' if changed == 'request' else
                'proposal.json' if changed == 'proposal' else 'generation.json')
    value = json.loads(artifacts[filename])
    fields = {'candidate': 'candidate_sha256', 'scope': 'scope', 'success': 'generation_executed',
              'agent': 'agent_execution', 'complete': 'complete', 'calls': 'model_calls'}
    if changed in fields:
        value[fields[changed]] = None
    elif changed == 'finish':
        value['choices'][0]['finish_reason'] = 'stop'
    elif changed == 'tokens':
        value['usage']['completion_tokens'] = True
    elif changed == 'request':
        value['messages'][0]['content'] = 'changed export'
    else:
        value['maximum_calls'] = 2
    artifacts[filename] = json.dumps(value).encode()
    with pytest.raises(ValueError):
        store.record_dataset_generation_failure(rid, artifacts=artifacts)


def test_native_generator_failure_persists_and_cannot_repeat_network(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from scripts.generate_receipt_evaluation import generate

    _, proposal = proposal_fixture(tmp_path, monkeypatch)
    (tmp_path / '.env').write_text('NEBIUS_API_KEY=offline-fixture-not-a-credential\n')
    requests, recorded = [], []

    def upstream(request):
        requests.append(request.url.path)
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data': [{'id': MODEL}]})
        return httpx.Response(200, json={
            'id': 'offline-fixture', 'object': 'chat.completion', 'created': 0, 'model': MODEL,
            'choices': [{'index': 0, 'finish_reason': 'length',
                         'message': {'role': 'assistant', 'content': 'incomplete reply'}}],
            'usage': {'prompt_tokens': 40, 'completion_tokens': 2000, 'total_tokens': 2040}})

    class OfflineClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault('transport', httpx.MockTransport(upstream))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, 'Client', OfflineClient)
    monkeypatch.setattr(httpx, 'HTTPTransport', lambda **kwargs:httpx.MockTransport(upstream))
    monkeypatch.setattr('scripts.generate_receipt_evaluation.ReviewStore',
        lambda root:SimpleNamespace(record_dataset_generation_failure=
            lambda rid, **kwargs:recorded.append((rid, kwargs))))
    report = generate(tmp_path, proposal)
    assert report['status'] == 'dataset_generation_failed'
    assert report['inference_executed'] is True and report['generation_executed'] is False
    assert report['model_calls'] == 1 and report['response_metadata']['finish_reason'] == 'length'
    assert 'dataset' not in report and len(recorded) == 1
    assert 'offline-fixture-not-a-credential' not in json.dumps(report)
    assert requests == ['/v1/models', '/v1/chat/completions']
    with pytest.raises(ValueError, match='already consumed'):
        generate(tmp_path, proposal)
    assert requests == ['/v1/models', '/v1/chat/completions']
