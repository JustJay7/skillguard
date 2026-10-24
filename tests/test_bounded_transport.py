import csv
import json

import httpx
import pytest

from skillguard.models.bounded_transport import (
    MODEL,
    AgentCallBudget,
    BoundedInferenceTransport,
)


def request(**overrides):
    payload = {
        "model": MODEL,
        "max_tokens": 1024,
        "stream": False,
        "messages": [{"role": "user", "content": "fake receipt"}],
        **overrides,
    }
    return httpx.Request(
        "POST", "https://api.tokenfactory.nebius.com/v1/chat/completions", json=payload
    )


def test_every_inference_is_costed_before_native_response_parsing(tmp_path):
    budget = AgentCallBudget(tmp_path / "cost.csv", tmp_path / "responses", max_calls=1)
    fake = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"usage": {"prompt_tokens": 100, "completion_tokens": 20}, "choices": []}
        )
    )
    transport = BoundedInferenceTransport(budget, fake)
    assert transport.handle_request(request()).status_code == 200
    rows = list(csv.DictReader(budget.ledger.open()))
    assert rows[0]["status"] == "completed"
    assert float(rows[0]["estimated_cost_usd"]) == pytest.approx(0.0000108)
    assert not rows[0]["reserved_cost_usd"]
    assert len(list(budget.responses.glob("*.json"))) == 1
    with pytest.raises(ValueError, match="request limit"):
        transport.handle_request(request())


@pytest.mark.parametrize(
    "changes",
    [
        {"stream": True},
        {"model": "unverified"},
        {"max_tokens": 100_000},
        {"max_tokens": True},
        {"max_tokens": None},
    ],
)
def test_unsafe_inference_parameters_never_reach_provider(tmp_path, changes):
    budget = AgentCallBudget(tmp_path / "cost.csv", tmp_path / "responses")
    transport = BoundedInferenceTransport(
        budget, httpx.MockTransport(lambda _: pytest.fail("must not call provider"))
    )
    with pytest.raises(ValueError):
        transport.handle_request(request(**changes))
    assert budget.calls == 0


def test_failed_request_retains_credit_reservation_and_hides_response(tmp_path):
    budget = AgentCallBudget(tmp_path / "cost.csv", tmp_path / "responses")
    transport = BoundedInferenceTransport(
        budget, httpx.MockTransport(lambda _: httpx.Response(401, text="sensitive provider error"))
    )
    with pytest.raises(RuntimeError, match="withheld") as error:
        transport.handle_request(request())
    assert "sensitive" not in str(error.value)
    row = list(csv.DictReader(budget.ledger.open()))[0]
    assert row["status"] == "http_401" and float(row["reserved_cost_usd"]) == 0.10
    assert not row["input_tokens"]


def test_unverified_endpoint_is_rejected(tmp_path):
    budget = AgentCallBudget(tmp_path / "cost.csv", tmp_path / "responses")
    transport = BoundedInferenceTransport(budget)
    with pytest.raises(ValueError, match="endpoint"):
        transport.handle_request(
            httpx.Request(
                "POST",
                "https://example.invalid/v1/chat/completions",
                json=json.loads(request().read()),
            )
        )
    assert budget.calls == 0
    transport.close()


def test_smaller_account_ceiling_includes_existing_reservations(tmp_path):
    ledger = tmp_path / "cost.csv"
    first = AgentCallBudget(ledger, tmp_path / "first", total_limit_usd=0.15)
    first.reserve()
    second = AgentCallBudget(ledger, tmp_path / "second", total_limit_usd=0.15)
    with pytest.raises(ValueError, match="credit budget"):
        second.reserve()
    assert second.calls == 0


def test_selected_super_model_is_costed_and_other_model_requests_are_refused(tmp_path):
    model = "nvidia/nemotron-3-super-120b-a12b"
    budget = AgentCallBudget(tmp_path / "cost.csv", tmp_path / "responses", model=model)
    transport = BoundedInferenceTransport(budget, httpx.MockTransport(lambda _: httpx.Response(
        200, json={"usage": {"prompt_tokens": 100, "completion_tokens": 20}, "choices": []})))
    with pytest.raises(ValueError):
        transport.handle_request(request())
    assert budget.calls == 0
    transport.handle_request(request(model=model))
    row = list(csv.DictReader(budget.ledger.open()))[0]
    assert row["model"] == model
    assert float(row["estimated_cost_usd"]) == pytest.approx(0.000048)


def test_provider_ledger_stays_private_with_permissive_process_umask(tmp_path):
    import os
    import stat

    budget = AgentCallBudget(tmp_path / 'cost.csv', tmp_path / 'responses')
    previous = os.umask(0)
    try:
        budget.reserve()
    finally:
        os.umask(previous)
    assert stat.S_IMODE(budget.ledger.stat().st_mode) == 0o600
