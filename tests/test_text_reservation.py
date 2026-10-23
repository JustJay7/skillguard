import csv
import json

import httpx
import pytest

from skillguard.models.bounded_transport import (
    MODEL,
    MODEL_RATES,
    TEXT_RESERVATION,
    AgentCallBudget,
    BoundedInferenceTransport,
    request_reservation,
    validate_text_request,
)
from skillguard.models.probe_claim import claim_probe


def payload():
    return {'model': MODEL, 'max_tokens': 2000, 'temperature': 0,
            'chat_template_kwargs': {'enable_thinking': False},
            'messages': [{'role': 'user', 'content': 'Fictional receipt input'}]}


@pytest.mark.parametrize('fault', ['size', 'count', 'tools', 'reasoning', 'image', 'role', 'n'])
def test_text_bound_rejects_expanding_inputs_before_reservation_or_http(tmp_path, fault):
    value = payload()
    if fault == 'size':
        value['messages'][0]['content'] = 'x' * 65_536
    elif fault == 'count':
        value['messages'] *= 33
    elif fault == 'tools':
        value['tools'] = [{'type': 'function'}]
    elif fault == 'reasoning':
        value['messages'][0]['reasoning_content'] = 'hidden expansion'
    elif fault == 'image':
        value['messages'][0]['content'] = [{'type': 'image_url'}]
    elif fault == 'role':
        value['messages'][0]['role'] = 'tool'
    else:
        value['n'] = 2
    budget = AgentCallBudget(tmp_path / 'cost.csv', tmp_path / 'responses',
        total_limit_usd=.75, reservation_profile=TEXT_RESERVATION)
    transport = BoundedInferenceTransport(budget, httpx.MockTransport(
        lambda request: pytest.fail('Rejected input must not reach the provider')))
    with pytest.raises(ValueError):
        transport.handle_request(httpx.Request('POST',
            'https://api.tokenfactory.nebius.com/v1/chat/completions', json=value))
    assert budget.calls == 0 and not budget.ledger.exists()


def test_short_text_hold_fits_cap_without_releasing_any_historical_unknown(tmp_path):
    ledger = tmp_path / 'cost.csv'
    from skillguard.models.bounded_transport import FIELDS

    with ledger.open('w') as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows([{'call_id': 'usage', 'estimated_cost_usd': '.12'},
                          {'call_id': 'unknown', 'reserved_cost_usd': '.25'}])
    claim_probe(ledger, tmp_path / 'claim.json', {'run_id': 'native',
        'maximum_model_requests': 6, 'reservation_profile': TEXT_RESERVATION})
    rows = list(csv.DictReader(ledger.open()))
    assert rows[1]['reserved_cost_usd'] == '.25'
    assert rows[2]['reserved_cost_usd'] == '0.06'
    assert request_reservation(MODEL, TEXT_RESERVATION) == .01
    assert request_reservation(MODEL, 'lightning-context-2026-10-22') == .075
    assert request_reservation(MODEL) == .1


def test_text_bound_accepts_unicode_without_normalizing_or_truncating_it():
    value = payload()
    value['messages'][0]['content'] = 'Montréal — receipt 23.00 ☕'
    raw = json.dumps(value, ensure_ascii=False).encode()
    before = json.dumps(value)
    validate_text_request(value, len(raw))
    assert json.dumps(value) == before


def test_changed_prices_cannot_silently_underreserve_text_calls(monkeypatch):
    monkeypatch.setitem(MODEL_RATES, MODEL, (1.0, 1.0))
    with pytest.raises(ValueError, match='reservation'):
        request_reservation(MODEL, TEXT_RESERVATION)
