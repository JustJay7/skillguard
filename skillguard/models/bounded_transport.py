"""Bound and account for each live HTTP inference request from the native agent."""

from __future__ import annotations

import csv
import fcntl
import json
import math
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

FIELDS = [
    "call_id",
    "time_utc",
    "model",
    "status",
    "input_tokens",
    "output_tokens",
    "estimated_cost_usd",
    "reserved_cost_usd",
    "latency_seconds",
]
MODEL = "nvidia/Nemotron-3_5-Lightning"
RATE_IN, RATE_OUT = 0.06, 0.24
MODEL_RATES = {MODEL: (RATE_IN, RATE_OUT), "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90)}
# Official Nebius Qwen inference pricing, checked 2026-10-30.
MODEL_RATES['Qwen/Qwen3-30B-A3B-Instruct-2507'] = (0.10, 0.30)
MAX_OUTPUT = 2048
CONTEXT_RESERVATION = 'lightning-context-2026-10-22'
TEXT_RESERVATION = 'lightning-text-64k-2026-10-23'
APP_COMPLETION_PROFILE = 'receipt-app-eight-request-2026-10-23'


def probe_request_limit(limit, app_profile=None) -> int:
    if type(limit) is not int or not (
            (limit in {4, 6} and app_profile is None)
            or (limit == 8 and app_profile == APP_COMPLETION_PROFILE)):
        raise ValueError('Unsupported native request bound/profile')
    return limit


TEXT_REQUEST_BYTES = 65_536
TEXT_INPUT_TOKEN_BOUND = 131_072


def request_reservation(model: str, profile: str = 'legacy') -> float:
    if profile == 'legacy':
        return .10
    if profile == TEXT_RESERVATION:
        if model != MODEL:
            raise ValueError('Text reservation requires the verified Lightning model')
        rates = MODEL_RATES[model]
        upper = (TEXT_INPUT_TOKEN_BOUND * rates[0] + MAX_OUTPUT * rates[1]) / 1e6
        if any(not math.isfinite(r) or r < 0 for r in rates) or upper > .01:
            raise ValueError('Bounded text request no longer fits its reservation')
        return .01
    if profile != CONTEXT_RESERVATION or model != MODEL:
        raise ValueError('Unknown reservation profile or model')
    # Nebius publishes 1,024K context and $0.06/$0.24 per million tokens:
    # https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference
    # Even full context PLUS the bounded output costs $0.06340608, below $0.075.
    upper = (1_048_576 * MODEL_RATES[model][0] + MAX_OUTPUT * MODEL_RATES[model][1]) / 1e6
    if any(not math.isfinite(r) or r < 0 for r in MODEL_RATES[model]) or upper > .075:
        raise ValueError('Published-context bound no longer fits the reservation')
    return .075


def validate_text_request(payload: dict, size: int) -> None:
    """Enforce the input proof before reserving or sending a short text call.

    NVIDIA's pinned Lightning tokenizer is byte-level BPE without normalization.
    With text-only role/content messages, no tools or reasoning fields, its chat
    template includes each content once and adds <128 bytes per message. 64 KiB
    plus 34*128 is <70k possible byte tokens; 131072 leaves further margin.
    Source proof and exact tokenizer/template hashes: docs/text-request-bound.md.
    """
    allowed = {'model', 'messages', 'max_tokens', 'temperature', 'chat_template_kwargs', 'stream'}
    messages = payload.get('messages')
    if (size > TEXT_REQUEST_BYTES or set(payload) - allowed or payload.get('model') != MODEL
            or payload.get('max_tokens') != 2000
            or payload.get('stream', False) is not False
            or payload.get('chat_template_kwargs') != {'enable_thinking': False}
            or not isinstance(messages, list) or not 1 <= len(messages) <= 32):
        raise ValueError('Request exceeds the verified bounded-text profile')
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                or message['role'] not in {'system', 'user', 'assistant'}
                or not isinstance(message['content'], str)):
            raise ValueError('Bounded text profile forbids non-text, tool and reasoning fields')
        message['content'].encode('utf-8', errors='strict')


class AgentCallBudget:
    def __init__(
        self, ledger: Path, responses: Path, *, max_calls: int = 3, total_limit_usd: float = 50,
        model: str = MODEL, reservation_profile: str = 'legacy',
    ) -> None:
        if not 0 < total_limit_usd <= 50:
            raise ValueError("credit limit must be positive and no more than the project ceiling")
        if model not in MODEL_RATES:
            raise ValueError("Unverified model rate configuration")
        self.model = model
        self.reservation_profile = reservation_profile
        self.request_reservation = request_reservation(model, reservation_profile)
        self.ledger, self.responses, self.max_calls = ledger, responses, max_calls
        self.total_limit_usd = total_limit_usd
        self.calls = 0
        self.guard = threading.Lock()
        responses.mkdir(parents=True, exist_ok=True)

    def update(self, row: dict, *, new: bool = False) -> None:
        with self.ledger.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.ledger.open() if self.ledger.exists() else open("/dev/null") as source:
                rows = list(csv.DictReader(source))
            if new:
                spent = sum(
                    float(r.get("reserved_cost_usd") or r.get("estimated_cost_usd") or 0)
                    for r in rows
                )
                if spent + self.request_reservation > self.total_limit_usd:
                    raise ValueError("total credit budget exhausted")
                rows.append(row)
            else:
                index = next(i for i, r in enumerate(rows) if r["call_id"] == row["call_id"])
                rows[index] = row
            with self.ledger.open("w", newline="") as output:
                os.fchmod(output.fileno(), 0o600)
                writer = csv.DictWriter(output, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

    def reserve(self) -> dict:
        with self.guard:
            if self.calls >= self.max_calls:
                raise ValueError("native agent probe request limit reached")
            row = dict.fromkeys(FIELDS, "")
            row.update(
                call_id=uuid.uuid4().hex,
                time_utc=datetime.now(UTC).isoformat(),
                model=self.model,
                status="reserved",
                reserved_cost_usd=self.request_reservation,
            )
            self.update(row, new=True)
            self.calls += 1
            return row


class BoundedInferenceTransport(httpx.BaseTransport):
    def __init__(
        self, budget: AgentCallBudget, upstream: httpx.BaseTransport | None = None
    ) -> None:
        self.budget = budget
        self.upstream = upstream or httpx.HTTPTransport(retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != "https"
            or request.url.host != "api.tokenfactory.nebius.com"
            or request.url.port not in {None, 443}
            or request.url.path != "/v1/chat/completions"
            or request.method != "POST"
            or request.url.query
        ):
            raise ValueError("agent probe only permits the verified inference endpoint")
        raw = request.read()
        if len(raw) > 80_000:
            raise ValueError("agent probe request exceeds its cost bound")
        payload = json.loads(raw)
        if self.budget.reservation_profile == TEXT_RESERVATION:
            validate_text_request(payload, len(raw))
        cap = payload.get("max_tokens", payload.get("max_completion_tokens"))
        if (
            payload.get("model") != self.budget.model
            or payload.get("stream", False)
            or type(cap) is not int
            or not 1 <= cap <= MAX_OUTPUT
        ):
            raise ValueError(
                "agent probe requires the catalog model and bounded nonstreaming output"
            )
        row = self.budget.reserve()
        start = time.monotonic()
        try:
            response = self.upstream.handle_request(request)
            response.read()
            metadata = self.budget.responses / 'transport'
            metadata.mkdir(exist_ok=True)
            (metadata / f"{row['call_id']}.json").write_text(json.dumps({
                'status_code': response.status_code,
                'headers': {k: response.headers[k] for k in (
                    'content-type', 'content-encoding', 'content-length', 'transfer-encoding')
                    if k in response.headers}}, indent=2) + '\n')
            row["status"] = f"http_{response.status_code}"
            if response.status_code != 200:
                raise RuntimeError("inference request failed; response body withheld")
            data = response.json()
            (self.budget.responses / f"{row['call_id']}.json").write_text(
                json.dumps(data, indent=2) + "\n"
            )
            usage = data["usage"]
            tokens_in, tokens_out = usage["prompt_tokens"], usage["completion_tokens"]
            if any(type(v) is not int or v < 0 for v in (tokens_in, tokens_out)):
                raise ValueError("invalid token usage; credit reservation retained")
            row.update(
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                estimated_cost_usd=(tokens_in * MODEL_RATES[self.budget.model][0]
                                    + tokens_out * MODEL_RATES[self.budget.model][1]) / 1_000_000,
                reserved_cost_usd="",
                status="completed",
            )
            return response
        except Exception:
            if row["status"] == "reserved":
                row["status"] = "failed_unknown_cost"
            raise
        finally:
            row["latency_seconds"] = time.monotonic() - start
            self.budget.update(row)

    def close(self) -> None:
        self.upstream.close()
