import asyncio
import csv
import gzip
import json

import httpx
import pytest
from tenacity import stop_after_attempt, wait_none

from skillguard.models.bounded_transport import MODEL, AgentCallBudget
from skillguard.models.harbor_transport import HarborRequestTransport, native_harbor_client


def budget(tmp_path, **kwargs):
    return AgentCallBudget(tmp_path / 'cost.csv', tmp_path / 'responses',
                           max_calls=kwargs.get('max_calls', 1), total_limit_usd=0.75)


def payload():
    return {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Fictional receipt only'}],
            'max_tokens': 2000, 'chat_template_kwargs': {'enable_thinking': False}}


@pytest.mark.parametrize('changed', ['thinking', 'missing', 'large', 'bool', 'alias', 'stream'])
def test_native_client_cannot_drop_request_bounds_or_forward_unsupported_modes(tmp_path, changed):
    calls = []
    guard = HarborRequestTransport(budget(tmp_path), httpx.MockTransport(
        lambda request: calls.append(request)))
    value = payload()
    if changed == 'thinking':
        value['chat_template_kwargs']['enable_thinking'] = True
    elif changed == 'missing':
        del value['chat_template_kwargs']
    elif changed == 'large':
        value['max_tokens'] = 2048
    elif changed == 'bool':
        value['chat_template_kwargs']['enable_thinking'] = 0
    elif changed == 'alias':
        value['max_completion_tokens'] = 3000
    else:
        value['stream'] = True
    with pytest.raises(ValueError):
        guard.handle_request(httpx.Request('POST',
            'https://api.tokenfactory.nebius.com/v1/chat/completions', json=value))
    assert not calls and guard.budget.calls == 0


@pytest.mark.parametrize('cloud', [False, True])
def test_actual_native_harbor_litellm_request_uses_bounded_sdk_and_exact_token_controls(
        tmp_path, cloud):
    from harbor.llms.lite_llm import LiteLLM

    calls = []
    account = budget(tmp_path, max_calls=8 if cloud else 1)

    def upstream(request):
        calls.append(json.loads(request.read()))
        return httpx.Response(200, json={'id': 'fake-only', 'created': 0,
            'object': 'chat.completion', 'model': MODEL,
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'Fictional answer'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}})

    async def native_call():
        async with native_harbor_client(account, api_key='fake-offline-key',
                                        upstream=httpx.MockTransport(upstream),
                compatibility_probe=cloud,
                app_execution_profile='receipt-app-eight-request-2026-10-23' if cloud else None,
                request_timeout_sec=60 if cloud else 30) as options:
            assert 'fake-offline-key' not in json.dumps(options)
            assert 'client' not in options
            client = LiteLLM(model_name='openai/' + MODEL,
                api_base='https://api.tokenfactory.nebius.com/v1', **options)
            response = await client.call('Fictional receipt only')
            assert response.content == 'Fictional answer'

    asyncio.run(native_call())
    assert len(calls) == 1 and account.calls == 1
    assert calls[0]['model'] == MODEL and calls[0]['max_tokens'] == 2000
    assert calls[0]['chat_template_kwargs'] == {'enable_thinking': False}
    assert 'fake-offline-key' not in json.dumps(calls)
    assert list(csv.DictReader((tmp_path / 'cost.csv').open()))[0]['status'] == 'completed'


def test_compressed_native_response_is_decoded_once_without_retry(tmp_path):
    from harbor.llms.lite_llm import LiteLLM

    account = budget(tmp_path)
    response = {'id': 'compressed-offline-only', 'created': 0,
        'object': 'chat.completion', 'model': MODEL,
        'choices': [{'index': 0, 'finish_reason': 'stop',
                     'message': {'role': 'assistant', 'content': 'Fictional answer'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}}
    compressed = gzip.compress(json.dumps(response).encode())

    def upstream(request):
        return httpx.Response(200, content=compressed, headers={
            'content-encoding': 'gzip', 'content-type': 'application/json',
            'content-length': str(len(compressed))})

    async def native_call():
        async with native_harbor_client(account, api_key='fake-offline-key',
                upstream=httpx.MockTransport(upstream)) as options:
            client = LiteLLM(model_name='openai/' + MODEL,
                api_base='https://api.tokenfactory.nebius.com/v1', **options)
            answer = await client.call('Fictional receipt only')
            assert answer.content == 'Fictional answer'

    asyncio.run(native_call())
    assert account.calls == 1
    assert list(csv.DictReader((tmp_path / 'cost.csv').open()))[0]['status'] == 'completed'


def test_native_retry_attempts_cannot_make_a_second_paid_http_request(tmp_path):
    from harbor.llms.lite_llm import LiteLLM
    from litellm import InternalServerError

    calls = []
    account = budget(tmp_path)

    def failing_upstream(request):
        calls.append(request)
        return httpx.Response(503, json={'error': {'message': 'Fictional offline failure'}})

    async def attempts():
        async with native_harbor_client(account, api_key='fake-offline-key',
                upstream=httpx.MockTransport(failing_upstream)) as options:
            client = LiteLLM(model_name='openai/' + MODEL,
                api_base='https://api.tokenfactory.nebius.com/v1', **options)
            # Preserve native retry behavior, but skip waits in this offline test.
            await client.call.retry_with(stop=stop_after_attempt(3), wait=wait_none())(
                client, 'Fictional receipt only')

    with pytest.raises(InternalServerError):
        asyncio.run(attempts())
    assert len(calls) == 1 and account.calls == 1
    assert list(csv.DictReader((tmp_path / 'cost.csv').open()))[0]['reserved_cost_usd'] == '0.1'


@pytest.mark.parametrize('fault', [
    'calls', 'six_without_profile', 'boolean_calls', 'aggregate', 'model'])
def test_native_sdk_cannot_initialize_with_expanded_budget_or_model(tmp_path, fault):
    account = budget(tmp_path)
    if fault == 'calls':
        account.max_calls = 5
    elif fault == 'six_without_profile':
        account.max_calls = 6
    elif fault == 'boolean_calls':
        account.max_calls = True
    elif fault == 'aggregate':
        account.total_limit_usd = 0.76
    else:
        account.model = 'nvidia/nemotron-3-super-120b-a12b'

    async def enter():
        async with native_harbor_client(account, api_key='fake-offline-key'):
            raise AssertionError('Expanded budget must be rejected before SDK construction')

    with pytest.raises(ValueError, match='limits'):
        asyncio.run(enter())
    assert account.calls == 0 and not (tmp_path / 'cost.csv').exists()


@pytest.mark.parametrize('limit', [6, 7])
def test_compatibility_profile_still_bounds_requests_before_sdk_initialization(tmp_path, limit):
    account = budget(tmp_path, max_calls=limit)

    async def enter():
        async with native_harbor_client(account, api_key='fake-offline-key',
                compatibility_probe=True, upstream=httpx.MockTransport(
                    lambda request: pytest.fail('No inference expected'))):
            return True

    if limit == 6:
        assert asyncio.run(enter()) is True
    else:
        with pytest.raises(ValueError, match='limits'):
            asyncio.run(enter())
    assert account.calls == 0 and not (tmp_path / 'cost.csv').exists()


@pytest.mark.parametrize('profile,compatibility,allowed', [(None, True, False),
    ('unknown', True, False), ('receipt-app-eight-request-2026-10-23', False, False),
    ('receipt-app-eight-request-2026-10-23', True, True)])
def test_eight_request_native_client_requires_the_explicit_app_profile(tmp_path, profile,
                                                                    compatibility, allowed):
    account = budget(tmp_path, max_calls=8)

    async def enter():
        async with native_harbor_client(account, api_key='fake-offline-key',
                upstream=httpx.MockTransport(lambda request: pytest.fail('No network call')),
                compatibility_probe=compatibility, app_execution_profile=profile) as options:
            assert options['num_retries'] == 0 and options['max_tokens'] == 2000
    if allowed:
        asyncio.run(enter())
    else:
        with pytest.raises(ValueError):
            asyncio.run(enter())
    assert account.calls == 0


def test_longer_provider_deadline_cannot_expand_the_legacy_client(tmp_path):
    async def enter():
        async with native_harbor_client(budget(tmp_path), api_key='fake-offline',
                                       request_timeout_sec=60):
            pytest.fail('Legacy profile cannot use the longer cloud deadline')
    with pytest.raises(ValueError, match='explicit app profile'):
        asyncio.run(enter())
