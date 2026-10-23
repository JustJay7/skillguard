import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from skillguard.review.store import ReviewStore
from skillguard.ui.server import handler_for, review_summary
from tests.test_recorded_agent_replay import replay, save


def test_ui_never_exposes_raw_artifacts_or_activates_stale_decision(tmp_path):
    store, rid, report, artifacts = replay(tmp_path)
    save(store, rid, report, artifacts)
    decision = store.decide(rid)
    summary = review_summary(store, rid)
    assert summary['decision'] == decision['decision'] == 'blocked'
    assert summary['decision_current'] and not summary['activation_permitted']
    assert str(tmp_path) not in json.dumps(summary)
    assert 'attachments' not in json.dumps(summary)
    store._append(rid, 'test_new_evidence', {'scope': 'offline fixture'})
    assert review_summary(store, rid)['decision'] == 'held'
    assert not review_summary(store, rid)['decision_current']


@pytest.fixture
def server(tmp_path):
    store, rid, _, _ = replay(tmp_path)
    store.decide(rid)
    service = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(store, rid))
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service, store, rid
    service.shutdown()
    service.server_close()
    thread.join()


def request(service, path, method='GET', headers=None):
    connection = http.client.HTTPConnection(*service.server_address, timeout=10)
    connection.request(method, path, headers=headers or {})
    response = connection.getresponse()
    result = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return result


def test_ui_routes_read_verified_store_and_block_remote_origins_and_writes(server):
    service, store, rid = server
    before = len(store.get(rid)['history'])
    for path in ('/', '/app.js', '/style.css', '/health', '/api/review'):
        status, raw, headers = request(service, path)
        assert status == 200 and raw
        assert headers['Cache-Control'] == 'no-store'
        assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert request(service, '/api/review', headers={'Host': 'evil.invalid'})[0] == 403
    assert request(service, '/api/review', headers={'Origin': 'https://evil.invalid'})[0] == 403
    for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        assert request(service, '/api/review', method)[0] == 405
    for path in ('/../../.env', '/api/review?path=.env', '/results/a'):
        assert request(service, path)[0] == 404
    assert len(store.get(rid)['history']) == before


def test_tampered_archive_returns_integrity_failure_instead_of_stale_pass(server):
    service, store, rid = server
    archive = Path(store.get(rid)['snapshot']) / 'scripts/parse_receipt.py'
    archive.write_bytes(b'CHANGED OFFLINE FIXTURE')
    status, raw, _ = request(service, '/api/review')
    assert status == 409 and b'activation held' in raw


def test_missing_review_is_not_substituted(tmp_path):
    with pytest.raises(KeyError):
        review_summary(ReviewStore(tmp_path / 'empty'), 'unknown')
