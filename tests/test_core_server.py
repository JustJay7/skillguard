import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from skillguard.ui.core_server import Application, handler_for


class Workspace:
    def summary(self):
        return {'reviews': [], 'active': None, 'previous': None, 'scope': 'offline fixture'}


@pytest.fixture
def service():
    app = Application(Workspace())
    calls = []
    app.start = lambda action, payload: calls.append((action, payload))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(app))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield app, server, calls
    server.shutdown()
    server.server_close()
    thread.join()


def request(service, path, *, method='GET', headers=None, body=None):
    _, server, _ = service
    connection = http.client.HTTPConnection(*server.server_address, timeout=10)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def test_core_ui_serves_local_assets_and_verified_state_only(service):
    for path in ('/', '/core.js', '/style.css', '/health', '/api/state'):
        status, raw, headers = request(service, path)
        assert status == 200 and raw
        assert headers['Cache-Control'] == 'no-store'
        assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert request(service, '/api/state', headers={'Host': 'evil.example'})[0] == 403
    assert request(service, '/api/state', headers={'Origin': 'https://evil.example'})[0] == 403
    assert request(service, '/../../.env')[0] == 404
    assert request(service, '/api/action', method='DELETE')[0] == 405
    health = json.loads(request(service, '/health')[1])
    assert health['status'] == 'listening' and health['deployment'] == 'local'
    assert health['provider']['status'] == 'missing_key'
    assert json.loads(request(service, '/api/state')[1])['connection'] == health['provider']


def test_demo_serves_only_allowlisted_read_only_assets(service, tmp_path, monkeypatch):
    import skillguard.ui.core_server as module

    monkeypatch.setattr(module, 'DEMO', tmp_path)
    assert request(service, '/demo/')[0] == 404
    for name in ('index.html', 'demo.js', 'demo.css', 'evidence.json', 'provenance.json'):
        (tmp_path / name).write_text('offline demo asset')
    for path in ('/demo/', '/demo/demo.js', '/demo/demo.css', '/demo/evidence.json',
                 '/demo/provenance.json'):
        assert request(service, path)[0] == 200
    (tmp_path / '.env').write_text('private')
    assert request(service, '/demo/.env')[0] == 404
    (tmp_path / 'evidence.json').unlink()
    (tmp_path / 'evidence.json').symlink_to(tmp_path / '.env')
    assert request(service, '/demo/evidence.json')[0] == 404
    app, server, calls = service
    assert request(service, '/demo/', method='POST', body='{}', headers={
        'Origin': f'http://127.0.0.1:{server.server_address[1]}',
        'X-SkillGuard-CSRF': app.token})[0] == 404
    assert not calls


@pytest.mark.parametrize('fault', ['origin', 'token', 'type', 'large', 'path', None])
def test_state_changing_actions_require_same_origin_token_and_bounded_json(service, fault):
    app, server, calls = service
    headers = {'Origin': f'http://127.0.0.1:{server.server_address[1]}',
               'X-SkillGuard-CSRF': app.token, 'Content-Type': 'application/json'}
    body = json.dumps({'action': 'approve', 'review_id': 'fixture',
                       'revision': 4, 'acknowledge_limits': True})
    if fault == 'origin':
        headers['Origin'] = 'https://evil.example'
    elif fault == 'token':
        headers['X-SkillGuard-CSRF'] = 'incorrect'
    elif fault == 'type':
        headers['Content-Type'] = 'text/plain'
    elif fault == 'large':
        body += ' ' * 40_000
    status, _, _ = request(service, '/api/action' if fault != 'path' else '/api/arbitrary',
                           method='POST', headers=headers, body=body)
    assert status == (202 if fault is None else 403 if fault in {'origin', 'token'}
                      else 404 if fault == 'path' else 409)
    assert len(calls) == int(fault is None)


def test_worker_failure_always_releases_busy_state_and_does_not_retry():
    import contextlib
    import subprocess

    class Broken(Workspace):
        calls = 0
        lock = staticmethod(contextlib.nullcontext)

        def test(self, rid):
            self.calls += 1
            raise subprocess.TimeoutExpired('offline fixture', 1)

    w = Broken()
    app = Application(w)
    app.start('test', {'review_id': 'fixture'})
    app.thread.join(timeout=10)
    assert app.job['status'] == 'failed' and w.calls == 1


def test_completion_cannot_be_combined_with_a_stale_installed_version():
    class Changing(Workspace):
        calls = 0

        def summary(self):
            self.calls += 1
            if self.calls == 1:
                app.job = {'action': 'rollback', 'status': 'done'}
                return {'active': 'old-version'}
            return {'active': 'restored-version'}

    w = Changing()
    app = Application(w)
    app.job = {'action': 'rollback', 'status': 'running'}
    value = app.state()
    assert value['job']['status'] == 'done' and value['active'] == 'restored-version'
    assert w.calls == 2
