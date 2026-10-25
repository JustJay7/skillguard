import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from scripts.judging_health import check as judging_health
from skillguard.ui.public_server import COOKIE, PublicEntry, handler_for

CODE = 'fictional-offline-access-code-at-least-32-characters'
ORIGIN = 'https://live.example'


class App:
    token = 'fixture-csrf'

    def __init__(self):
        self.calls = []

    def state(self):
        return {'reviews': [], 'learning': {'private_archive': True}, 'csrf': self.token}

    def start(self, action, payload):
        self.calls.append((action, payload))


@pytest.fixture
def public(tmp_path):
    origin = tmp_path / 'origin.txt'
    origin.write_text(ORIGIN)
    entry = PublicEntry(App(), origin, CODE)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(entry))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield entry, server
    server.shutdown()
    server.server_close()
    thread.join()


def request(public, path, *, method='GET', headers=None, payload=None):
    _, server = public
    h = {'Host': 'live.example', **(headers or {})}
    if payload is not None:
        h['Content-Type'] = 'application/json'
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    connection.request(method, path, headers=h,
                       body=json.dumps(payload) if payload is not None else None)
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def login(public):
    status, body, headers = request(public, '/api/login', method='POST',
        headers={'Origin': ORIGIN}, payload={'code': CODE})
    assert status == 200 and json.loads(body)['authenticated']
    cookie = headers['Set-Cookie']
    assert all(flag in cookie for flag in ['Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/'])
    return cookie.split(';')[0]


def test_anonymous_users_cannot_read_runtime_state_code_or_trigger_actions(public):
    assert b'not a replay' in request(public, '/')[1]
    assert request(public, '/api/state')[0] == 401
    assert request(public, '/core.js')[0] == 401
    assert request(public, '/.env')[0] == 401
    status, body, _ = request(public, '/api/action', method='POST',
        headers={'Origin': ORIGIN}, payload={'action': 'review_security'})
    assert status == 403 and CODE.encode() not in body
    assert not public[0].app.calls
    assert json.loads(request(public, '/health')[1])['depends_on_mac'] is True


def test_authenticated_state_is_current_without_private_comparison_archive(public):
    cookie = login(public)
    status, raw, _ = request(public, '/api/state', headers={'Cookie': cookie})
    state = json.loads(raw)
    assert status == 200 and state['learning'] is None
    assert state['public_hosting']['mode'] == 'local_tunnel'
    assert CODE.encode() not in raw and cookie.encode() not in raw
    html = request(public, '/', headers={'Cookie': cookie})[1]
    assert b'PUBLIC LIVE BACKEND' in html and b'href="/demo/"' not in html
    assert b'<details hidden><summary>Review your own receipt skill' in html
    assert request(public, '/.env', headers={'Cookie': cookie})[0] == 404


@pytest.mark.parametrize('fault', ['host', 'origin', 'cookie', 'csrf', 'import', 'path', None])
def test_public_paid_or_approval_actions_require_all_boundaries(public, fault):
    cookie = login(public)
    headers = {'Origin': ORIGIN, 'Cookie': cookie, 'X-SkillGuard-CSRF': 'fixture-csrf'}
    if fault == 'host':
        headers['Host'] = 'attacker.example'
    if fault == 'origin':
        headers['Origin'] = 'https://attacker.example'
    if fault == 'cookie':
        headers['Cookie'] = COOKIE + '=forged'
    if fault == 'csrf':
        headers['X-SkillGuard-CSRF'] = 'wrong'
    status, _, _ = request(public, '/unknown' if fault == 'path' else '/api/action',
        method='POST', headers=headers,
        payload={'action': 'import' if fault == 'import' else 'review_security'})
    assert status == (202 if fault is None else 404 if fault in {'path', 'import'} else 403)
    assert len(public[0].app.calls) == int(fault is None)


def test_login_throttle_and_missing_or_unsafe_origin_fail_closed(public):
    entry, _ = public
    for _ in range(10):
        assert entry.login('wrong') is None
    assert entry.login(CODE) is None
    entry.origin_file.write_text('https://live.example@attacker.example/path')
    assert request(public, '/health')[0] == 403
    entry.origin_file.unlink()
    assert request(public, '/')[0] == 403


def test_cloud_hosting_labels_keep_idle_limits_visible(public):
    entry, _ = public
    entry.hosting_mode = 'codespaces'
    health = json.loads(request(public, '/health')[1])
    assert health['mode'] == 'codespaces' and health['depends_on_mac'] is False
    login_html = request(public, '/')[1]
    assert b'idle shutdown limits apply' in login_html
    assert b"operator's Mac" not in login_html
    cookie = login(public)
    html = request(public, '/', headers={'Cookie': cookie})[1]
    assert b'GitHub Codespaces' in html and b'quota is exhausted' in html
    assert b'running on this Mac' not in html
    assert entry.state()['public_hosting']['depends_on_mac'] is False


def test_dedicated_host_keeps_auth_and_origin_without_codespaces_proxy_exception(public):
    entry, server = public
    entry.hosting_mode = 'linux_vm'
    health = json.loads(request(public, '/health')[1])
    assert health['mode'] == 'linux_vm' and health['depends_on_mac'] is False
    assert request(public, '/api/state')[0] == 401
    login_html = request(public, '/')[1]
    assert b'dedicated Linux' in login_html and b"operator's Mac" not in login_html
    cookie = login(public)
    html = request(public, '/', headers={'Cookie': cookie})[1]
    assert b'Dedicated Linux cloud host' in html
    assert b'GitHub Codespaces' not in html and b'running on this Mac' not in html
    headers = {'Origin': ORIGIN, 'Cookie': cookie, 'X-SkillGuard-CSRF': 'fixture-csrf'}
    assert request(public, '/api/action', method='POST', headers=headers,
                   payload={'action': 'review_security'})[0] == 202
    headers['Origin'] = 'https://attacker.example'
    assert request(public, '/api/action', method='POST', headers=headers,
                   payload={'action': 'review_security'})[0] == 403
    headers.update({'Host': f'localhost:{server.server_address[1]}',
        'X-Forwarded-Host': 'live.example', 'X-Forwarded-Proto': 'https',
        'Origin': f'http://localhost:{server.server_address[1]}',
        'X-SkillGuard-Origin': ORIGIN})
    assert request(public, '/api/action', method='POST', headers=headers,
                   payload={'action': 'review_security'})[0] == 403
    assert len(entry.app.calls) == 1


def test_judging_health_uses_only_loopback_and_refuses_the_old_host(public, monkeypatch):
    entry, server = public
    entry.hosting_mode = 'linux_vm'
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    judging_health(entry.origin_file, port=server.server_address[1])
    assert not entry.app.calls and not entry.sessions
    entry.hosting_mode = 'codespaces'
    with pytest.raises(ValueError, match='Expected protected'):
        judging_health(entry.origin_file, port=server.server_address[1])
    entry.origin_file.write_text('https://attacker.example/redirect')
    with pytest.raises(ValueError, match='Configured HTTPS'):
        judging_health(entry.origin_file, port=server.server_address[1])
    assert not entry.app.calls


@pytest.mark.parametrize('fault', [None, 'forwarded', 'port', 'origin', 'cookie', 'mode'])
def test_codespaces_proxy_requires_exact_loopback_host_origin_and_session(public, fault):
    entry, server = public
    entry.hosting_mode = 'codespaces'
    cookie = login(public)
    headers = {'Host': f'localhost:{server.server_address[1]}', 'X-Forwarded-Host': 'live.example',
        'X-Forwarded-Proto': 'https',
        'Origin': ORIGIN, 'Cookie': cookie, 'X-SkillGuard-CSRF': 'fixture-csrf'}
    if fault == 'forwarded':
        headers['X-Forwarded-Host'] = 'attacker.example'
    elif fault == 'port':
        headers['Host'] = 'localhost:1'
    elif fault == 'origin':
        headers['Origin'] = 'https://attacker.example'
    elif fault == 'cookie':
        headers.pop('Cookie')
    elif fault == 'mode':
        entry.hosting_mode = 'local_tunnel'
    status, _, _ = request(public, '/api/action', method='POST', headers=headers,
                           payload={'action': 'review_security'})
    assert status == (202 if fault is None else 403)
    assert len(entry.app.calls) == int(fault is None)


@pytest.mark.parametrize('fault', [None, 'marker', 'proto', 'origin', 'csrf', 'cookie'])
def test_rewritten_origin_requires_same_origin_marker_and_unchanged_auth(public, fault):
    entry, server = public
    entry.hosting_mode = 'codespaces'
    cookie = login(public)
    headers = {'Host': f'localhost:{server.server_address[1]}', 'X-Forwarded-Host': 'live.example',
        'X-Forwarded-Proto': 'https', 'Origin': f'http://localhost:{server.server_address[1]}',
        'X-SkillGuard-Origin': ORIGIN, 'Cookie': cookie, 'X-SkillGuard-CSRF': 'fixture-csrf'}
    if fault == 'marker':
        headers.pop('X-SkillGuard-Origin')
    elif fault == 'proto':
        headers['X-Forwarded-Proto'] = 'http'
    elif fault == 'origin':
        headers['Origin'] = 'https://attacker.example'
    elif fault == 'csrf':
        headers['X-SkillGuard-CSRF'] = 'wrong'
    elif fault == 'cookie':
        headers.pop('Cookie')
    status, _, _ = request(public, '/api/action', method='POST', headers=headers,
                           payload={'action': 'review_security'})
    assert status == (202 if fault is None else 403)
    assert len(entry.app.calls) == int(fault is None)
    assert request(public, '/api/action', method='OPTIONS', headers=headers)[0] == 501
