from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from skillguard.models.bounded_transport import MODEL


def load_responses(folder: Path) -> list[bytes]:
    manifest = json.loads((folder / 'manifest.json').read_text())
    items = manifest['responses']
    if not 1 <= len(items) <= 4 or len({i['name'] for i in items}) != len(items):
        raise ValueError('Recorded response count/identity differs')
    result = []
    for item in items:
        name = item['name']
        if Path(name).name != name or not name.endswith('.json'):
            raise ValueError('Recorded response path is unsafe')
        raw = (folder / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Recorded response changed')
        value = json.loads(raw)
        if value['model'] != MODEL or len(value['choices']) != 1:
            raise ValueError('Recorded provider identity differs')
        result.append(raw)
    return result


class RecordedResponses(httpx.BaseTransport):
    def __init__(self, folder: Path):
        self.responses = load_responses(folder)
        self.consumed = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.consumed >= len(self.responses):
            raise ValueError('Recorded responses exhausted; no network fallback')
        raw = self.responses[self.consumed]
        self.consumed += 1
        return httpx.Response(200, content=raw, headers={'content-type': 'application/json'})
