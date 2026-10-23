"""Run one reviewed native generation request, with exact export and cost bounds.

This command needs human authorization for the prepared fixture-text export.
It generates questions only; no agent, candidate execution, repair or activation.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from dotenv import dotenv_values
from openai import OpenAI

from scripts.learned_candidate_image import candidate_payload
from scripts.prepare_generated_receipt_evaluation import GUIDANCE, native_generation_options
from skillguard.models.bounded_transport import (
    MODEL,
    AgentCallBudget,
    BoundedInferenceTransport,
)
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


class ReviewedGenerationTransport(BoundedInferenceTransport):
    def __init__(self, budget: AgentCallBudget, payload: dict,
                 upstream: httpx.BaseTransport | None = None) -> None:
        super().__init__(budget, upstream)
        self.payload = payload

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if json.loads(request.read()) != self.payload:
            raise ValueError("Native generation request differs from the reviewed export")
        response = super().handle_request(request)
        choices = response.json().get('choices') or []
        if choices and choices[0].get('finish_reason') == 'length':
            raise ValueError('Native generation exhausted its reviewed output-token limit')
        return response


def validate_proposal(root: Path, proposal_path: Path) -> tuple[dict, dict]:
    proposal_path = proposal_path.resolve()
    if not proposal_path.is_relative_to(root / "results/integration"):
        raise ValueError("Proposal must be an archived local integration result")
    proposal = json.loads(proposal_path.read_text())
    request = Path(proposal["proposed_request"]).resolve()
    skill = Path(proposal["skill"]).resolve()
    if request.parent != proposal_path.parent or skill.parent != proposal_path.parent:
        raise ValueError("Proposed export escaped its archived directory")
    if digest(request.read_bytes()) != proposal["proposed_request_sha256"]:
        raise ValueError("Proposed export changed")
    candidate = candidate_payload(root, Path(proposal["preparation"]))
    if candidate["candidate_sha256"] != proposal["candidate_sha256"]:
        raise ValueError("Proposal belongs to another candidate")
    for name, encoded in candidate["files"].items():
        if (skill / name).read_bytes() != base64.b64decode(encoded):
            raise ValueError("Native generator context differs from the frozen candidate")
    if (skill / "evals/EVAL.md").read_text() != GUIDANCE:
        raise ValueError("Proposed generation guidance changed")
    files = {p.relative_to(skill).as_posix() for p in skill.rglob("*") if p.is_file()}
    if files != set(candidate["files"]) | {"evals/EVAL.md"}:
        raise ValueError("Native generator context contains unexpected files")
    payload = json.loads(request.read_text())
    if payload.get("model") != MODEL or payload.get("max_tokens") != 2000:
        raise ValueError("Proposed model/output bound changed")
    expected_options = {'enable_thinking': False} if proposal.get('direct_answer') else None
    if payload.get('chat_template_kwargs') != expected_options:
        raise ValueError("Reviewed native reasoning option changed")
    return proposal, payload


def claim_proposal(root: Path, proposal: dict, run: Path) -> Path:
    """Consume a one-call request across invocations, including crashed ones.

    Operator-owned storage is not attestation. New claims survive missing run
    reports; recorded legacy paid attempts also consume authorization.
    """
    identity = proposal['proposed_request_sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('Invalid reviewed request identity')
    for path in (root / 'results/integration').glob('generated-receipt-eval-*/generation.json'):
        previous = json.loads(path.read_text())
        if previous.get('proposed_request_sha256') == identity and previous.get('model_calls', 0):
            raise ValueError('Reviewed generation request already consumed its single call')
    folder = root / 'results/generation-claims'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    claim = folder / (identity + '.json')
    try:
        with claim.open('x') as output:
            output.write(json.dumps({'request_sha256': identity,
                'candidate_sha256': proposal['candidate_sha256'], 'run': str(run),
                'maximum_calls': 1, 'status': 'claimed_before_network'}, indent=2) + '\n')
    except FileExistsError as error:
        raise ValueError(
            'Reviewed generation request already claimed; no automatic retry') from error
    claim.chmod(0o400)
    return claim


def response_metadata(responses: Path) -> dict:
    """Report provider completion state without exporting its generated content."""
    files = list(responses.glob('*.json'))
    if not files:
        return {'response_recorded': False}
    if len(files) != 1:
        raise ValueError('Expected one archived generation response')
    raw = files[0].read_bytes()
    response = json.loads(raw)
    choices = response.get('choices') or []
    finish = choices[0].get('finish_reason') if choices else None
    return {'response_recorded': True, 'response_sha256': digest(raw),
            'finish_reason': finish, 'usage': response.get('usage'),
            'failure_kind': 'output_token_limit' if finish == 'length' else None}


def generate(root: Path, proposal_path: Path) -> dict:
    from skillevaluator.inference.client import LLMClient
    from skillevaluator.tier3.generate_dataset import (
        _generate_with_llm,
        _parse_skill,
        _to_agentskills_dataset,
    )

    proposal, payload = validate_proposal(root, proposal_path)
    key = dotenv_values(root / ".env").get("NEBIUS_API_KEY", "")
    if not key:
        raise RuntimeError("Private inference credential missing")
    run = root / "results/integration" / f"generated-receipt-eval-{uuid.uuid4().hex[:8]}"
    claim = claim_proposal(root, proposal, run)
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        response = client.get("https://api.tokenfactory.nebius.com/v1/models",
                              headers={"Authorization": "Bearer " + key})
        response.raise_for_status()
        if MODEL not in {item["id"] for item in response.json()["data"]}:
            raise RuntimeError("Prepared model is absent from the current account catalog")
    run.mkdir(mode=0o700)
    budget = AgentCallBudget(root / "results/cost_log.csv", run / "responses",
                             max_calls=1, total_limit_usd=0.75, model=MODEL)
    environment = {
        "SKILL_EVAL_LLM_PROVIDER": "openai-compatible",
        "SKILL_EVAL_LLM_MODEL": MODEL,
        "SKILL_EVAL_LLM_BASE_URL": "https://api.tokenfactory.nebius.com/v1",
        "SKILL_EVAL_LLM_API_KEY": key,
    }
    report = {"run_id": run.name, "candidate_sha256": proposal["candidate_sha256"],
              "proposal": str(proposal_path.resolve()), "model": MODEL,
              "proposed_request_sha256": proposal["proposed_request_sha256"],
              "generation_executed": False, "agent_execution": False,
              "claim": str(claim), "status": "generation_pending",
              "activation_permitted": False, "complete": False,
              "scope": "Native generated questions; no measured resistance or Skill Lift"}
    try:
        with (
            httpx.Client(transport=ReviewedGenerationTransport(budget, payload),
                         timeout=60, trust_env=False, follow_redirects=False) as http_client,
            OpenAI(api_key=key, base_url=environment["SKILL_EVAL_LLM_BASE_URL"],
                   max_retries=0, http_client=http_client) as sdk,
            patch.dict(os.environ, environment),
            patch.object(LLMClient, "_get_client", return_value=sdk),
            native_generation_options(sdk, direct_answer=proposal.get('direct_answer', False)),
        ):
            skill = _parse_skill(Path(proposal["skill"]))
            cases = asyncio.run(_generate_with_llm(skill, full=True,
                fallback_to_template=False, announce_provider=False))
        dataset = run / "evals.json"
        dataset.write_text(json.dumps(_to_agentskills_dataset(skill["name"], cases),
                                       indent=2, ensure_ascii=False) + "\n")
        dataset.chmod(0o400)
        report.update(generation_executed=True, dataset=str(dataset), cases=len(cases),
                      dataset_sha256=digest(dataset.read_bytes()), status='dataset_produced')
    except Exception as error:
        # Upstream diagnostics can mention fixture prompts; preserve privately.
        report["error"] = str(error)
        report['status'] = 'dataset_generation_failed'
    finally:
        report["model_calls"] = budget.calls
        report['response_metadata'] = response_metadata(run / 'responses')
        report['inference_executed'] = budget.calls > 0
        (run / "generation.json").write_text(json.dumps(report, indent=2) + "\n")
        (run / "generation.json").chmod(0o600)
        if (report.get('error')
                and report['response_metadata'].get('failure_kind') == 'output_token_limit'):
            parent = json.loads(Path(proposal['preparation']).read_text())
            response = next((run / 'responses').glob('*.json'))
            ReviewStore(Path(parent['store'])).record_dataset_generation_failure(
                parent['review_id'], artifacts={
                    'generation.json': (run / 'generation.json').read_bytes(),
                    'proposal.json': proposal_path.read_bytes(),
                    'request.json': Path(proposal['proposed_request']).read_bytes(),
                    'response.json': response.read_bytes()})
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", type=Path, required=True)
    args = parser.parse_args()
    report = generate(Path(__file__).resolve().parents[1], args.proposal)
    print(json.dumps(report, indent=2))
    if report.get('error'):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
