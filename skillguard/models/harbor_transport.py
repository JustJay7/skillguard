"""HTTP integration for native Harbor/LiteLLM, with existing ledger bounds.

No replacement agent loop or live-job entry point. Caller owns authorization and
credential confinement; tests use only fake keys and recorded HTTP responses.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from skillguard.models.bounded_transport import MODEL, AgentCallBudget, BoundedInferenceTransport


class HarborRequestTransport(BoundedInferenceTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        if (type(payload.get('max_tokens')) is not int or payload['max_tokens'] != 2000
                or 'max_completion_tokens' in payload
                or payload.get('chat_template_kwargs') != {'enable_thinking': False}
                or type(payload['chat_template_kwargs']['enable_thinking']) is not bool):
            raise ValueError('Native Harbor probe requires 2000 output tokens '
                             'and thinking disabled')
        return super().handle_request(request)


class AsyncHarborTransport(httpx.AsyncBaseTransport):
    def __init__(self, bounded: HarborRequestTransport):
        self.bounded = bounded

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        response = await asyncio.to_thread(self.bounded.handle_request, request)
        # The sync client already decoded compressed bytes. Reusing its encoding
        # header asks httpx to decompress plain JSON a second time.
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() not in {'content-encoding', 'content-length', 'transfer-encoding'}}
        return httpx.Response(response.status_code, headers=headers,
                              content=response.content, request=request)

    async def aclose(self):
        await asyncio.to_thread(self.bounded.close)


@asynccontextmanager
async def native_harbor_client(budget: AgentCallBudget, *, api_key: str,
                               upstream: httpx.BaseTransport | None = None,
                               compatibility_probe: bool = False,
                               authorized_limit_usd: float = .75):
    """Yield SDK kwargs consumed by the installed native Harbor LiteLLM client.

    Count actual HTTP requests, including hidden native/SDK retries. This primitive
    does not authorize a job, pass credentials to a container or implement a relay.
    """
    if type(compatibility_probe) is not bool:
        raise ValueError('Native Harbor compatibility flag must be boolean')
    ceiling = 6 if compatibility_probe else 4
    if (budget.model != MODEL or not 0 < budget.total_limit_usd <= authorized_limit_usd <= 50
            or type(budget.max_calls) is not int or not 1 <= budget.max_calls <= ceiling):
        raise ValueError('Native Harbor probe exceeds the current aggregate/request limits')
    transport = AsyncHarborTransport(HarborRequestTransport(budget, upstream))
    from litellm.llms.openai.openai import OpenAIChatCompletion

    async with (
        httpx.AsyncClient(transport=transport, timeout=30, trust_env=False,
                          follow_redirects=False) as client,
        AsyncOpenAI(api_key=api_key, base_url='https://api.tokenfactory.nebius.com/v1',
                    max_retries=0, http_client=client) as sdk,
    ):
        def guarded_client(_self, is_async, api_key=None, api_base=None, **kwargs):
            if is_async is not True or api_base is None or api_base.rstrip('/') != (
                    'https://api.tokenfactory.nebius.com/v1'):
                raise ValueError('Native Harbor client requested an unreviewed endpoint/mode')
            return sdk

        # Native Terminus includes llm_kwargs in ATIF metadata. Keep SDK/key objects
        # out of those serializable settings and intercept only its provider client.
        with patch.object(OpenAIChatCompletion, '_get_openai_client', guarded_client):
            yield {'max_tokens': 2000, 'num_retries': 0,
                   'extra_body': {'chat_template_kwargs': {'enable_thinking': False}}}
