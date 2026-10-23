import hashlib
import json

import httpx
import pytest

from skillguard.models.bounded_transport import MODEL
from skillguard.models.recorded_responses import RecordedResponses, load_responses


def fixture(folder):
    raw = json.dumps({'model': MODEL, 'choices': [{'message': {'content': 'retained'}}]}).encode()
    (folder / 'reply.json').write_bytes(raw)
    manifest = {'responses': [{'name': 'reply.json',
                             'sha256': hashlib.sha256(raw).hexdigest()}]}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return raw, manifest


def test_exact_recorded_bytes_exhaust_without_network_fallback(tmp_path):
    raw, _ = fixture(tmp_path)
    transport = RecordedResponses(tmp_path)
    request = httpx.Request('POST', 'https://api.tokenfactory.nebius.com/v1/chat/completions')
    assert transport.handle_request(request).content == raw
    with pytest.raises(ValueError, match='exhausted'):
        transport.handle_request(request)


@pytest.mark.parametrize('change', ['bytes', 'path', 'count', 'duplicate', 'model'])
def test_recorded_response_manifest_rejects_changed_or_unsafe_input(tmp_path, change):
    _, manifest = fixture(tmp_path)
    item = manifest['responses'][0]
    if change == 'bytes':
        (tmp_path / item['name']).write_text('{}')
    elif change == 'path':
        item['name'] = '../reply.json'
    elif change == 'count':
        manifest['responses'] = []
    elif change == 'duplicate':
        manifest['responses'].append(item)
    else:
        raw = json.dumps({'model': 'other', 'choices': [{}]}).encode()
        (tmp_path / item['name']).write_bytes(raw)
        item['sha256'] = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_responses(tmp_path)
