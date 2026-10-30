"""Exercise the authenticated cloud research action without recording credentials."""
from __future__ import annotations

import json
import os
import subprocess
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    origin_file = root / 'results/public-hosting/origin.txt'
    access_file = root / 'results/public-hosting/access-code.txt'
    origin = origin_file.read_text().strip()
    headers = {'Host': urlsplit(origin).netloc, 'Origin': origin,
               'X-SkillGuard-Origin': origin}
    with httpx.Client(base_url='http://127.0.0.1:8770', headers=headers,
                      timeout=60, trust_env=False) as client:
        try:
            client.get('/')
        except httpx.ConnectError:
            env = dict(os.environ)
            env['PATH'] = ('/workspaces/work/lima/bin:/workspaces/work/semgrep-venv/bin:'
                '/workspaces/work/skillspector-venv/bin:/workspaces/work/bin:'
                + str(root / '.venv/bin') + ':' + env.get('PATH', ''))
            with (root / 'results/research-runtime-server.log').open('a') as log:
                subprocess.Popen([str(root / '.venv/bin/python'), '-m',
                    'skillguard.ui.public_server', '--origin-file', str(origin_file),
                    '--access-file', str(access_file), '--hosting-mode', 'codespaces'],
                    cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(40):
                try:
                    client.get('/')
                    break
                except httpx.ConnectError:
                    time.sleep(.25)
        login = client.post('/api/login', json={'code': access_file.read_text().strip()})
        login.raise_for_status()
        cookies = SimpleCookie()
        cookies.load(login.headers['set-cookie'])
        client.headers['Cookie'] = '; '.join(f'{k}={v.value}' for k, v in cookies.items())
        for _ in range(60):
            state = client.get('/api/state').json()
            if state.get('job', {}).get('status') != 'running':
                break
            time.sleep(.5)
        client.headers['X-SkillGuard-CSRF'] = state['csrf']
        response = client.post('/api/action', json={'action': 'research_threats'})
        response.raise_for_status()
        for _ in range(90):
            state = client.get('/api/state').json()
            if state['job']['status'] != 'running':
                break
            time.sleep(.5)
        assert state['job']['status'] == 'done', state['job']
        research = state['threat_research']
        assert research['provider'] == 'Tavily' and research['sources']
        html = client.get('/').text
        assert 'Research attack coverage' in html
        from skillguard.threat_research import probe_guidance

        guidance = probe_guidance(root)
        assert guidance and research['categories']
        report = {'passed': True, 'action': 'research_threats',
            'authenticated_http_action_status': response.status_code,
            'provider': research['provider'], 'usage': research['usage'],
            'request_id': research['request_id'], 'sources': research['sources'],
            'categories': research['categories'], 'prospective_probe_guidance': guidance,
            'external_text_is_permission_authority': False,
            'scope': 'Real Tavily call through the authenticated application action. '
                     'Categories inform future generation; existing native trials are unchanged.'}
        (root / 'results/oct30-tavily-runtime-verification.json').write_text(
            json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
