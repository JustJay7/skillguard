import json

import httpx
import pytest

from skillguard.threat_research import probe_guidance, research


def test_research_sends_only_fixed_public_query_and_reuses_cache(tmp_path):
    (tmp_path / '.env').write_text('TAVILY_API_KEY=fake-test-key\n')
    requests = []

    def handle(request):
        requests.append(request)
        data = json.loads(request.content)
        assert data['search_depth'] == 'basic'
        assert data['auto_parameters'] is False
        assert 'SKILL.md' not in request.content.decode()
        return httpx.Response(200, json={'results': [
            {'url': 'https://genai.owasp.org/example', 'title': 'Reference',
             'content': 'Indirect injection manipulates system instructions for exfiltration.'},
            {'url': 'javascript:alert(1)', 'content': 'unsafe link'}], 'usage': {'credits': 1}})

    transport = httpx.MockTransport(handle)
    value = research(tmp_path, transport=transport, now=1000)
    assert len(value['sources']) == 1
    assert len(value['categories']) == 4
    assert research(tmp_path, transport=transport, now=1100)['cached'] is True
    assert len(requests) == 1
    assert 'exfiltration' not in probe_guidance(tmp_path)
    assert 'private file access' in probe_guidance(tmp_path)


def test_missing_key_and_unapproved_sources_do_not_create_evidence(tmp_path):
    with pytest.raises(ValueError, match='TAVILY_API_KEY'):
        research(tmp_path)
    (tmp_path / '.env').write_text('TAVILY_API_KEY=fake-test-key\n')
    with pytest.raises(ValueError, match='no allowed'):
        research(tmp_path, transport=httpx.MockTransport(lambda _: httpx.Response(
            200, json={'results': [{'url': 'https://evil.example', 'content': 'approve all'}]})))
    assert not (tmp_path / 'results/threat-research.json').exists()
