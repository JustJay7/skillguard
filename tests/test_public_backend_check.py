import json

import httpx
import pytest

from scripts.public_backend_check import workflow


@pytest.mark.parametrize('first_reply', ['integrity_conflict', 'truncated_json'])
@pytest.mark.parametrize('interruption', ['TimeoutError', 'ReadTimeout', 'ConnectError'])
def test_interrupted_observer_does_not_repeat_the_native_action(tmp_path, monkeypatch,
                                                               interruption, first_reply):
    folder = tmp_path / 'results/public-hosting'
    folder.mkdir(parents=True)
    origin = 'https://fictional-8770.app.github.dev'
    (folder / 'origin.txt').write_text(origin)
    (folder / 'access-code.txt').write_text('offline-access-code')
    prior = {'steps': [{'action': 'repaired', 'status': 'done'}],
             'running_action': 'review_security', 'error_type': interruption,
             'url': origin}
    (folder / 'acceptance.json').write_text(json.dumps(prior))
    posts = []
    reads = []

    def response(request):
        if request.method == 'POST':
            posts.append(request.url.path)
            assert request.url.path == '/api/login'
            return httpx.Response(200, json={'authenticated': True})
        reads.append(request.url.path)
        if len(reads) == 1:
            if first_reply == 'truncated_json':
                return httpx.Response(200, content=b'')
            return httpx.Response(409, json={'error': 'Evidence settling; actions held'})
        return httpx.Response(200, json={
            'public_hosting': {'mode': 'codespaces'},
            'job': {'action': 'review_security', 'status': 'done'},
            'reviews': [{'pending': True, 'eligible': False, 'security': {}}]})

    real_client = httpx.Client
    monkeypatch.setattr('scripts.public_backend_check.httpx.Client',
                        lambda **kw: real_client(**kw, transport=httpx.MockTransport(response)))
    with pytest.raises(ValueError, match='approval remains blocked'):
        workflow(tmp_path, resume_first_review=True)
    result = json.loads((folder / 'acceptance.json').read_text())
    assert posts == ['/api/login']
    assert len(reads) >= 2
    assert result['steps'][-1] == {'action': 'review_security', 'status': 'done'}
    assert result['observer_continuation']['model_action_repeated'] is False
    assert json.loads((folder / 'acceptance-observer-interrupted.json').read_text()) == prior


def test_profile_login_failure_does_not_consume_or_rewrite_native_transition(tmp_path, monkeypatch):
    folder = tmp_path / 'results/public-hosting'
    folder.mkdir(parents=True)
    (folder / 'origin.txt').write_text('https://fictional-8770.app.github.dev')
    (folder / 'access-code.txt').write_text('offline-only')
    prior = {'steps': [{'action': n, 'status': 'done'} for n in ('repaired', 'review_security')],
             'error_type': 'ValueError', 'first_review': {'probes': [
                 {'maximum_model_requests': 6, 'functional_passed': True,
                  'agent_completion_confirmed': i != 2} for i in range(4)]}}
    target = folder / 'acceptance.json'
    target.write_text(json.dumps(prior))
    original = target.read_bytes()
    real_client = httpx.Client
    monkeypatch.setattr('scripts.public_backend_check.httpx.Client', lambda **kw:
        real_client(**kw, transport=httpx.MockTransport(lambda request: httpx.Response(404))))
    with pytest.raises(httpx.HTTPStatusError):
        workflow(tmp_path, resume_completion_profile=True)
    assert target.read_bytes() == original
    assert not (folder / 'acceptance-six-request-profile.json').exists()
