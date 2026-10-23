"""Check the real provider connection without inference or credential disclosure."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

MODELS = ('nvidia/Nemotron-3_5-Lightning', 'nvidia/nemotron-3-super-120b-a12b')
CATALOG = 'https://api.tokenfactory.nebius.com/v1/models'


def configuration(root: Path | None) -> dict:
    key = dotenv_values(root / '.env').get('NEBIUS_API_KEY') if root else None
    return {'deployment': 'local', 'provider': 'Nebius Token Factory',
            'key_configured': bool(key), 'status': 'not_checked' if key else 'missing_key',
            'checked_at': None, 'models': {}, 'inference_requests': 0,
            'sandbox': 'Local OpenShell; starts on demand for native actions'}


def check_provider(root: Path, *, transport=None) -> dict:
    result = configuration(root)
    result['checked_at'] = datetime.now(UTC).isoformat()
    if not result['key_configured']:
        return result
    key = dotenv_values(root / '.env')['NEBIUS_API_KEY']
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False,
                          transport=transport) as client:
            response = client.get(CATALOG, headers={'Authorization': 'Bearer ' + key})
        result['http_status'] = response.status_code
        if response.status_code == 200:
            models = {m['id'] for m in response.json()['data']}
            result['models'] = {name: name in models for name in MODELS}
            result['status'] = ('connected' if all(result['models'].values())
                                else 'missing_models')
        else:
            result['status'] = ('rejected_key' if response.status_code in {401, 403}
                                else 'unavailable')
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        result['status'] = 'unavailable'
    return result
