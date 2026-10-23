import json

import httpx
import pytest

from skillguard.live_status import CATALOG, MODELS, check_provider


def test_real_catalog_check_authenticates_only_to_fixed_provider_and_never_returns_key(tmp_path):
    key = 'fictional-offline-key'
    (tmp_path / '.env').write_text('NEBIUS_API_KEY=' + key)
    calls = []

    def handle(request):
        calls.append(request)
        assert str(request.url) == CATALOG
        assert request.headers['Authorization'] == 'Bearer ' + key
        return httpx.Response(200, json={'data': [{'id': m} for m in MODELS]})

    result = check_provider(tmp_path, transport=httpx.MockTransport(handle))
    assert result['status'] == 'connected' and result['checked_at']
    assert result['inference_requests'] == 0 and len(calls) == 1
    assert key not in json.dumps(result)


@pytest.mark.parametrize('case', ['missing', 'unauthorized', 'redirect', 'timeout',
                                 'malformed', 'missing_model'])
def test_unready_provider_never_reports_connected_or_discloses_responses(tmp_path, case):
    key = 'fictional-offline-key'
    if case != 'missing':
        (tmp_path / '.env').write_text('NEBIUS_API_KEY=' + key)
    calls = []

    def handle(request):
        calls.append(request)
        if case == 'timeout':
            raise httpx.ReadTimeout(key, request=request)
        if case == 'malformed':
            return httpx.Response(200, text=key)
        if case == 'missing_model':
            return httpx.Response(200, json={'data': [{'id': MODELS[0]}]})
        return httpx.Response(401 if case == 'unauthorized' else 302,
                              text=key, headers={'Location': 'https://example.com'})

    result = check_provider(tmp_path, transport=httpx.MockTransport(handle))
    assert result['status'] != 'connected'
    assert key not in json.dumps(result)
    assert len(calls) == (0 if case == 'missing' else 1)
