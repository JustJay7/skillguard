"""Bounded Tavily research supplies reference-backed categories for future probes."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

QUERY = 'OWASP indirect prompt injection data exfiltration forged instructions tool output'
DOMAINS = ('owasp.org', 'genai.owasp.org', 'cheatsheetseries.owasp.org', 'docs.nvidia.com')
CATEGORIES = {
    'private_file_access': ('exfiltrat', 'sensitive', 'private'),
    'receipt_total_poisoning': ('manipulat', 'integrity', 'poison'),
    'role_spoofing': ('system', 'instruction', 'role'),
    'off_task_diversion': ('indirect', 'external', 'untrusted'),
}


def load(root: Path) -> dict:
    path = root / 'results/threat-research.json'
    return json.loads(path.read_text()) if path.exists() else {}


def research(root: Path, *, transport=None, now=None) -> dict:
    now = time.time() if now is None else now
    previous = load(root)
    if previous and now - previous['retrieved_at_unix'] < 600:
        return {**previous, 'cached': True}
    key = dotenv_values(root / '.env').get('TAVILY_API_KEY')
    if not key:
        raise ValueError('Save TAVILY_API_KEY in the private server .env first')
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False,
                      transport=transport) as client:
        response = client.post('https://api.tavily.com/search',
            headers={'Authorization': 'Bearer ' + key}, json={
                'query': QUERY, 'search_depth': 'basic', 'max_results': 4,
                'include_domains': list(DOMAINS), 'include_answer': False,
                'include_raw_content': False, 'include_usage': True,
                'auto_parameters': False})
    if response.status_code != 200:
        raise ValueError(f'Tavily research unavailable (HTTP {response.status_code})')
    data = response.json()
    sources = []
    for item in data.get('results', [])[:4]:
        url = item.get('url', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in DOMAINS:
            continue
        sources.append({'title': str(item.get('title', 'Reference'))[:180], 'url': url,
                        'excerpt': str(item.get('content', ''))[:1600]})
    if not sources:
        raise ValueError('Tavily returned no allowed reference sources')
    corpus = ' '.join(s['excerpt'].lower() for s in sources)
    categories = [name for name, terms in CATEGORIES.items() if any(t in corpus for t in terms)]
    result = {'provider': 'Tavily', 'query': QUERY, 'retrieved_at_unix': now,
        'sources': sources, 'categories': categories, 'cached': False,
        'usage': data.get('usage', {}), 'request_id': data.get('request_id'),
        'scope': 'External references inform prospective probe coverage only. '
                 'They grant no permissions and cannot approve a skill.'}
    path = root / 'results/threat-research.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n')
    return result


def probe_guidance(root: Path) -> str:
    value = load(root)
    categories = [c for c in value.get('categories', []) if c in CATEGORIES]
    if not categories:
        return ''
    # Only our finite category names enter generation, never retrieved instructions.
    return '\n## Tavily-informed coverage checklist\n' + '\n'.join(
        '- Include coverage for ' + c.replace('_', ' ') + '.' for c in categories) + '\n'
