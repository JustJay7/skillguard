from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from skillguard.review.store import ReviewStore

ASSETS = Path(__file__).parent


def review_summary(store: ReviewStore, review_id: str) -> dict:
    review = store.get(review_id)
    latest = review['latest']
    decision = latest.get('decision', {})
    current_revision = review['history'][-1]['seq'] if review['history'] else 0
    decision_current = (decision.get('candidate_sha256') == review['candidate_sha256']
                        and decision.get('evidence_revision') == current_revision - 1
                        and review['history'][-1]['kind'] == 'decision'
                        ) if current_revision else False
    live = latest.get('live_agent_trial', {})
    enforced_live = latest.get('enforced_live_agent_trial', {})
    replay = latest.get('recorded_agent_replay', {})
    enforced = latest.get('enforced_agent_replay', {})
    captured = latest.get('agent_capture', {})
    functional = latest.get('frozen_resource_evaluation', {}).get('frozen_splits', {})
    comparison = latest.get('candidate_process_comparison', {})
    return {'review_id': review_id, 'skill': review['name'],
        'candidate_sha256': review['candidate_sha256'], 'revision': current_revision,
        'decision': decision.get('decision', 'held') if decision_current else 'held',
        'decision_current': decision_current, 'activation_permitted': False,
        'reasons': decision.get('reasons', []) if decision_current else [
            'Evidence changed since the saved decision; a new review is required'],
        'pending_removed': latest.get('rejection', {}).get('pending_removed', False),
        'archive_preserved': latest.get('rejection', {}).get('archive_preserved', False),
        'static': latest.get('static', {}).get('overall_status', 'not_run'),
        'functional_splits': {name: {'passed': item['passed'],
            'cases': len(item.get('cases', {}))} for name, item in functional.items()},
        'live': {k: live.get(k) for k in ('native_agent_steps', 'model_requests',
            'completed_domain_cases', 'functional_passed', 'terminal_fake_canary_disclosure')},
        'recorded': {k: replay.get(k) for k in ('native_agent_steps',
            'terminal_fake_canary_disclosure', 'model_requests')},
        'capture': {k: captured.get(k) for k in ('reported_read_bytes',
            'reported_private_file_reads', 'scoped_projected_events')},
        'enforced': {k: enforced.get(k) for k in ('native_agent_steps',
            'private_file_open_denied', 'native_sandbox_stopped', 'recomputed_grade', 'scope')},
        'enforced_capture': enforced.get('capture', {}),
        'enforced_live': {k: enforced_live.get(k) for k in ('native_agent_steps',
            'model_requests', 'functional_passed', 'terminal_fake_canary_disclosure',
            'native_skill_discovery', 'scope')},
        'behavior': comparison.get('diff', {}),
        'behavior_scope': comparison.get('scope', 'No independent comparison available'),
        'behavior_limitations': comparison.get('limitations', []),
        'history': [{'sequence': e['seq'], 'kind': e['kind'], 'sha256': e['sha256']}
                    for e in review['history']],
        'scope': 'Fictional receipt tests. Recorded command replay is separate from fresh '
                 'model inference. Partial evidence cannot authorize activation.'}


def handler_for(store: ReviewStore, review_id: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def send(self, status, raw, content_type='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            port = self.server.server_address[1]
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if (self.headers.get('Host') not in allowed or
                    self.headers.get('Origin') not in {None, *(f'http://{a}' for a in allowed)}):
                self.send(403, b'{"error":"Local review access only"}')
                return
            if self.path == '/api/review':
                try:
                    raw = json.dumps(review_summary(store, review_id)).encode()
                except (ValueError, KeyError, OSError):
                    self.send(409, b'{"error":"Review integrity check failed; activation held"}')
                    return
                self.send(200, raw)
            elif self.path == '/health':
                self.send(200, b'{"status":"ready","mode":"read-only"}')
            elif self.path in {'/', '/app.js', '/style.css'}:
                name, mime = {'/': ('index.html', 'text/html; charset=utf-8'),
                    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                    '/style.css': ('style.css', 'text/css; charset=utf-8')}[self.path]
                self.send(200, (ASSETS / name).read_bytes(), mime)
            else:
                self.send(404, b'{"error":"Unknown route"}')

        def do_POST(self):
            self.send(405, b'{"error":"This review interface is read-only"}')

        do_PUT = do_DELETE = do_PATCH = do_POST

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--review', required=True)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    store = ReviewStore(args.store)
    review_summary(store, args.review)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(store, args.review))
    server.serve_forever()


if __name__ == '__main__':
    main()
