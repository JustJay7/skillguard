from __future__ import annotations

import argparse
import json
import secrets
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from skillguard.core import CoreWorkspace

ASSETS = Path(__file__).parent
DEMO = Path(__file__).resolve().parents[2] / 'dist/skillguard-demo'


class Application:
    def __init__(self, workspace):
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        self.guard = threading.Lock()
        self.job = None
        self.thread = None

    def state(self):
        while True:
            with self.guard:
                job = self.job
            summary = self.workspace.summary()
            with self.guard:
                if job is self.job:
                    return {**summary, 'csrf': self.token, 'job': job}

    def start(self, action, payload):
        if action not in {'stage', 'update', 'unsafe', 'test', 'approve', 'reject',
                          'rollback', 'run', 'test_agent', 'repaired', 'run_agent',
                          'review_security', 'import', 'repair_and_review', 'resume_security',
                          'escalate_security'}:
            raise ValueError('Unknown action')
        with self.guard:
            if self.job and self.job['status'] == 'running':
                raise ValueError('A workspace operation is already running')
            self.job = {'action': action, 'status': 'running'}

        def worker():
            try:
                w = self.workspace
                with w.lock():
                    if action in {'stage', 'update', 'unsafe', 'repaired'}:
                        result = {'review_id': w.stage_example(update=(action == 'update'
                            or action in {'unsafe', 'repaired'} and bool(w.installed()['active'])),
                            unsafe=action == 'unsafe', repaired=action == 'repaired')}
                    elif action == 'import':
                        result = {'review_id': w.stage_example(
                            update=bool(w.installed()['active']), repaired=True,
                            content=payload['content'])}
                    elif action in {'review_security', 'repair_and_review', 'resume_security',
                                    'escalate_security'}:
                        def progress(message):
                            with self.guard:
                                self.job = {**self.job, 'message': message}

                        rid = payload['review_id']
                        if action == 'repair_and_review':
                            blocked = w.store.get(rid)
                            if blocked['latest'].get('security_review', {}).get(
                                    'decision') != 'blocked':
                                raise ValueError('Repair requires a blocked security review')
                            w.reject(rid, revision=payload['revision'])
                            repaired = w.stage_example(update=bool(w.installed()['active']),
                                                       repaired=True)
                            w.store._append(repaired, 'repair_lineage', {
                                'parent_review_id': rid,
                                'parent_candidate_sha256': blocked['candidate_sha256'],
                                'method': 'Known receipt repair recipe; new probes required'})
                            rid = repaired
                        if action == 'escalate_security':
                            from skillguard.security_review import escalate

                            if rid not in w.detect():
                                raise ValueError('Only a current pending skill can be adjudicated')
                            result = escalate(w, rid, progress)
                        else:
                            result = w.review_security(rid, progress,
                                                       resume=action == 'resume_security')
                    elif action == 'test':
                        result = w.test(payload['review_id'])
                    elif action == 'test_agent':
                        result = w.test_agent(payload['review_id'])
                    elif action == 'approve':
                        result = w.approve(payload['review_id'], revision=payload['revision'],
                                          acknowledge_limits=payload.get('acknowledge_limits'),
                                          accept_model_hold=payload.get('accept_model_hold', False),
                                          operator_reason=payload.get('operator_reason'))
                    elif action == 'reject':
                        result = w.reject(payload['review_id'], revision=payload['revision'])
                    elif action == 'rollback':
                        result = w.rollback(expected_active=payload['expected_active'])
                    elif action == 'run_agent':
                        result = w.run_installed_agent(expected_active=payload['expected_active'])
                    else:
                        result = w.run_receipt(payload['text'])
                # Raw native paths/logs stay in the operator's evidence store.
                fields = ('receipt', 'version', 'model_requests') if action == 'run' else (
                    'answer', 'version', 'model_requests', 'candidate_sha256', 'run_id',
                    'skill_use', 'agent_completion_confirmed')
                public = ({k: result.get(k) for k in fields}
                          if action in {'run', 'run_agent'} else {'completed': True})
                self.job = {'action': action, 'status': 'done', 'result': public}
            except Exception as error:
                self.job = {'action': action, 'status': 'failed',
                            'error': str(error)[:300]}

        self.thread = threading.Thread(target=worker)
        self.thread.start()


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def local(self, *, write=False):
            port = self.server.server_address[1]
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            origin = self.headers.get('Origin')
            return (self.headers.get('Host') in hosts
                    and origin in ({f'http://{h}' for h in hosts} if write else {
                        None, *(f'http://{h}' for h in hosts)}))

        def send(self, status, value, mime='application/json'):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; "
                             "object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.local():
                self.send(403, {'error': 'Local workspace access only'})
            elif self.path == '/api/state':
                try:
                    self.send(200, app.state())
                except (ValueError, KeyError, OSError):
                    self.send(409, {'error': 'Evidence or installed version changed; actions held'})
            elif self.path == '/health':
                self.send(200, {'status': 'ready', 'mode': 'restricted-receipt-workspace'})
            elif self.path in {'/demo/', '/demo/demo.js', '/demo/demo.css',
                               '/demo/evidence.json', '/demo/provenance.json'}:
                name, mime = {
                    '/demo/': ('index.html', 'text/html; charset=utf-8'),
                    '/demo/demo.js': ('demo.js', 'text/javascript; charset=utf-8'),
                    '/demo/demo.css': ('demo.css', 'text/css; charset=utf-8'),
                    '/demo/evidence.json': ('evidence.json', 'application/json'),
                    '/demo/provenance.json': ('provenance.json', 'application/json')}[self.path]
                path = DEMO / name
                if path.is_file() and not path.is_symlink():
                    self.send(200, path.read_bytes(), mime)
                else:
                    self.send(404, {'error': 'Build the recorded demo with make demo-bundle'})
            elif self.path in {'/', '/core.js', '/style.css'}:
                name, mime = {'/': ('core.html', 'text/html; charset=utf-8'),
                    '/core.js': ('core.js', 'text/javascript; charset=utf-8'),
                    '/style.css': ('style.css', 'text/css; charset=utf-8')}[self.path]
                self.send(200, (ASSETS / name).read_bytes(), mime)
            else:
                self.send(404, {'error': 'Unknown route'})

        def do_POST(self):
            if (not self.local(write=True)
                    or not secrets.compare_digest(self.headers.get('X-SkillGuard-CSRF', ''),
                                                  app.token)):
                self.send(403, {'error': 'Local approval session required'})
                return
            if self.path != '/api/action':
                self.send(404, {'error': 'Unknown route'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if (not 0 < length <= 40_000
                        or self.headers.get('Content-Type') != 'application/json'):
                    raise ValueError('A bounded JSON request is required')
                payload = json.loads(self.rfile.read(length))
                app.start(payload['action'], payload)
                self.send(202, {'status': 'started'})
            except (ValueError, KeyError, TypeError):
                self.send(409, {'error': 'Invalid action or another operation is running'})

        def do_PUT(self):
            self.send(405, {'error': 'Unsupported method'})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, default=Path('results/core'))
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    app = Application(CoreWorkspace(root, args.workspace))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(app))
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if app.thread:
            app.thread.join()


if __name__ == '__main__':
    main()
