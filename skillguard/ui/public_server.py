"""Authenticated public entry to an isolated, real local SkillGuard workspace."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import threading
import time
from collections import deque
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from skillguard.core import CoreWorkspace
from skillguard.ui.core_server import ASSETS, Application

COOKIE = '__Host-skillguard-session'
ACTIONS = {'stage', 'update', 'unsafe', 'repaired', 'review_security', 'repair_and_review',
           'resume_security', 'escalate_security', 'approve', 'reject', 'rollback',
           'run_agent', 'check_connection', 'research_threats'}
LOGIN = b'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SkillGuard live backend</title><link rel="stylesheet" href="/style.css">
<main><header><strong>SkillGuard</strong><span>Live security review</span></header>
<h1>Test what your agent learns.</h1><p>This is the real backend, with native
OpenShell execution and real Nebius model calls. It runs on the operator's Mac;
that computer and its connection must remain available. This is not a replay.</p>
<section><h2>Enter the demo access code</h2><p>Access protects model credits and
installation controls. The shared demo uses fictional receipt skills only.</p>
<form id="login"><label for="code">Access code</label>
<input id="code" type="password" autocomplete="off" required>
<button>Open live workspace</button></form><p id="error" role="alert"></p></section>
<p>No API key is sent to your browser. Do not enter personal receipts or credentials.</p>
</main><script src="/login.js" defer></script></html>'''
LOGIN_JS = b'''document.getElementById('login').addEventListener('submit',async e=>{
e.preventDefault();const error=document.getElementById('error');error.textContent='';
try {const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json',
'X-SkillGuard-Origin':location.origin},
body:JSON.stringify({code:document.getElementById('code').value})});
if(!r.ok)throw Error('Access denied or too many attempts. Check your code and try again.');
location.replace('/');}catch(e){error.textContent=e.message;}});'''


class PublicEntry:
    def __init__(self, app, origin_file: Path, access_code: str, *, hosting_mode='local_tunnel'):
        if len(access_code) < 32:
            raise ValueError('A strong private access code is required')
        if hosting_mode not in {'local_tunnel', 'codespaces', 'linux_vm'}:
            raise ValueError('Explicit supported hosting mode required')
        self.hosting_mode = hosting_mode
        self.app, self.origin_file = app, origin_file
        self.code_hash = hashlib.sha256(access_code.encode()).digest()
        self.sessions = {}
        self.attempts = deque()
        self.guard = threading.Lock()
        self.last_connection_check = 0

    def origin(self):
        try:
            raw = self.origin_file.read_text().strip()
            u = urlsplit(raw)
            if (u.scheme != 'https' or not u.hostname or u.username or u.password
                    or u.path not in {'', '/'} or u.query or u.fragment):
                return None
            return 'https://' + u.netloc
        except (OSError, ValueError):
            return None

    def login(self, code):
        now = time.monotonic()
        with self.guard:
            while self.attempts and self.attempts[0] < now - 60:
                self.attempts.popleft()
            if len(self.attempts) >= 10:
                return None
            self.attempts.append(now)
            if not isinstance(code, str) or not secrets.compare_digest(
                    self.code_hash, hashlib.sha256(code.encode()).digest()):
                return None
            self.sessions = {k: v for k, v in self.sessions.items() if v > now}
            if len(self.sessions) >= 20:
                return None
            token = secrets.token_urlsafe(32)
            self.sessions[token] = now + 8 * 3600
            return token

    def authorized(self, header):
        try:
            cookies = SimpleCookie()
            cookies.load(header or '')
            token = cookies[COOKIE].value
        except (KeyError, ValueError, CookieError):
            return False
        with self.guard:
            return self.sessions.get(token, 0) > time.monotonic()

    def state(self):
        value = self.app.state()
        value['learning'] = None
        if self.hosting_mode in {'codespaces', 'linux_vm'} and 'connection' in value:
            value['connection'] = {**value['connection'], 'deployment': self.hosting_mode,
                'sandbox': 'Isolated cloud OpenShell VM; starts on demand for native actions'}
        value['public_hosting'] = {'mode': self.hosting_mode,
                                   'depends_on_mac': self.hosting_mode == 'local_tunnel',
                                   'anonymous_actions': False}
        # Public workspace reviews are independent; never serve the private store.
        return value


def handler_for(entry):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *args):
            return

        def send(self, status, value, mime='application/json', *, session=None):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            for name, content in {'Content-Type': mime, 'Content-Length': str(len(raw)),
                    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                    'Referrer-Policy': 'no-referrer', 'Content-Security-Policy':
                    "default-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'self'"}.items():
                self.send_header(name, content)
            if session:
                self.send_header('Set-Cookie', f'{COOKIE}={session}; Path=/; Secure; '
                                 'HttpOnly; SameSite=Strict; Max-Age=28800')
            self.end_headers()
            self.wfile.write(raw)

        def target_allowed(self, *, write=False):
            origin = entry.origin()
            if not origin:
                return False
            expected = urlsplit(origin).netloc
            direct = self.headers.get('Host') == expected
            proxy = (entry.hosting_mode == 'codespaces'
                and self.client_address[0] == '127.0.0.1'
                and self.headers.get('Host') == f'localhost:{self.server.server_address[1]}'
                and self.headers.get('X-Forwarded-Host') == expected
                and self.headers.get('X-Forwarded-Proto') == 'https')
            supplied = self.headers.get('Origin')
            allowed = supplied in ({origin} if write else {None, origin})
            # GitHub rewrites Origin as well as Host. The same-origin script's
            # explicit header survives that rewrite; cross-origin browser code
            # cannot send it because this server grants no CORS preflight.
            mapped = (write and proxy
                and supplied == f'http://localhost:{self.server.server_address[1]}'
                and self.headers.get('X-SkillGuard-Origin') == origin)
            return bool((direct or proxy) and (allowed or mapped))

        def do_GET(self):
            if not self.target_allowed():
                self.send(403, {'error': 'Configured HTTPS origin required'})
                return
            authenticated = entry.authorized(self.headers.get('Cookie'))
            if self.path == '/health':
                self.send(200, {'status': 'listening', 'mode': entry.hosting_mode,
                                'depends_on_mac': entry.hosting_mode == 'local_tunnel',
                                'authentication_required': True})
            elif self.path in {'/style.css', '/login.js'}:
                raw = LOGIN_JS if self.path == '/login.js' else (ASSETS / 'style.css').read_bytes()
                self.send(200, raw, 'text/javascript' if self.path.endswith('.js') else 'text/css')
            elif self.path == '/' and not authenticated:
                login = LOGIN
                if entry.hosting_mode == 'codespaces':
                    login = login.replace(b"It runs on the operator's Mac;\nthat computer and its "
                        b'connection must remain available.', b'It runs in a dedicated GitHub '
                        b'Codespace with an isolated Linux VM. The cloud workspace must be '
                        b'running; included usage and idle shutdown limits apply.')
                elif entry.hosting_mode == 'linux_vm':
                    login = login.replace(b"It runs on the operator's Mac;\nthat computer and its "
                        b'connection must remain available.', b'It runs on a dedicated Linux '
                        b'cloud host with an isolated OpenShell VM. Host availability and '
                        b'provider credits are required.')
                self.send(200, login, 'text/html; charset=utf-8')
            elif not authenticated:
                self.send(401, {'error': 'Demo access code required'})
            elif self.path == '/api/state':
                try:
                    self.send(200, entry.state())
                except (ValueError, KeyError, OSError):
                    self.send(409, {'error': 'Evidence changed; actions held'})
            elif self.path == '/':
                html = (ASSETS / 'core.html').read_text()
                html = '\n'.join(line for line in html.splitlines() if 'href="/demo/"' not in line)
                html = html.replace('<details><summary>Review your own receipt skill',
                                    '<details hidden><summary>Review your own receipt skill')
                html = html.replace('<label for="receipt">', '<div hidden><label for="receipt">')
                html = html.replace('<div id="output" aria-live="polite"></div></details>',
                                    '<div id="output" aria-live="polite"></div></div></details>')
                location = {'codespaces': 'GitHub Codespaces · '
                        'stops when idle or quota is exhausted',
                    'linux_vm': 'Dedicated Linux cloud host',
                    'local_tunnel': 'Runs on the operator’s Mac'}[entry.hosting_mode]
                html = html.replace('<main>', '<main><p class="note">PUBLIC LIVE BACKEND · '
                    + location + ' · fictional shared demo workspace · '
                    'actual model calls and native sandbox execution</p>', 1)
                if entry.hosting_mode in {'codespaces', 'linux_vm'}:
                    running = ('Live app · running in GitHub Codespaces'
                        if entry.hosting_mode == 'codespaces'
                        else 'Live app · running in the cloud')
                    html = html.replace('Live app · running on this Mac', running)
                    html = html.replace('this local app owns the real review and installation '
                        'controls.', 'this protected cloud workspace owns the real review and '
                        'installation controls.')
                self.send(200, html.encode(), 'text/html; charset=utf-8')
            elif self.path == '/core.js':
                self.send(200, (ASSETS / 'core.js').read_bytes(), 'text/javascript')
            else:
                self.send(404, {'error': 'Unknown route'})

        def do_POST(self):
            if not self.target_allowed(write=True):
                self.send(403, {'error': 'Same-origin HTTPS request required'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Bounded JSON required')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('JSON object required')
                if self.path == '/api/login':
                    token = entry.login(payload.get('code'))
                    self.send(200 if token else 401, {'authenticated': bool(token)}, session=token)
                    return
                if (not entry.authorized(self.headers.get('Cookie')) or not secrets.compare_digest(
                        self.headers.get('X-SkillGuard-CSRF', ''), entry.app.token)):
                    self.send(403, {'error': 'Authenticated approval session required'})
                    return
                if self.path != '/api/action' or payload.get('action') not in ACTIONS:
                    self.send(404, {'error': 'Unsupported public action'})
                    return
                if payload['action'] == 'check_connection':
                    with entry.guard:
                        now = time.monotonic()
                        if now - entry.last_connection_check < 60:
                            self.send(429, {'error': 'Connection check already performed recently'})
                            return
                        entry.last_connection_check = now
                entry.app.start(payload['action'], payload)
                self.send(202, {'status': 'started'})
            except (ValueError, KeyError, TypeError):
                self.send(409, {'error': 'Invalid request or another operation is running'})

        def do_PUT(self):
            self.send(405, {'error': 'Unsupported method'})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin-file', type=Path, required=True)
    parser.add_argument('--access-file', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--hosting-mode', choices=['local_tunnel', 'codespaces', 'linux_vm'],
                        default='local_tunnel')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    results = root / 'results'
    if results.is_symlink():
        raise ValueError('Private operator results directory required')
    results.mkdir(exist_ok=True, mode=0o700)
    results.chmod(0o700)
    os.umask(0o077)
    if args.access_file.is_symlink() or args.access_file.stat().st_mode & 0o077:
        raise ValueError('Regular access-code file with private permissions required')
    app = Application(CoreWorkspace(root, root / 'results/public-core'))
    entry = PublicEntry(app, args.origin_file, args.access_file.read_text().strip(),
                        hosting_mode=args.hosting_mode)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(entry))
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    app.start('check_connection', {})
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if app.thread:
            app.thread.join()


if __name__ == '__main__':
    main()
