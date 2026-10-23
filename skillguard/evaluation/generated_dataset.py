"""Delegate recorded-response parsing to the installed native dataset generator."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch


def native_recorded_dataset(skill_name: str, content: str) -> dict:
    """Use the native parser/normalizer with a response cache and no network.

    Native generation handles cardinality, fields and default security assertions.
    This checks reproducibility, not case quality or adversarial resistance.
    """
    from skillevaluator.inference.client import LLMClient
    from skillevaluator.tier3.generate_dataset import _generate_with_llm, _to_agentskills_dataset

    skill = {'name': skill_name, 'description': '', 'scripts': []}
    environment = {'SKILL_EVAL_LLM_PROVIDER': 'openai-compatible',
        'SKILL_EVAL_LLM_MODEL': 'nvidia/Nemotron-3_5-Lightning',
        'SKILL_EVAL_LLM_BASE_URL': 'https://api.tokenfactory.nebius.com/v1',
        'SKILL_EVAL_LLM_API_KEY': 'offline-recorded-response-not-a-credential'}
    with patch.dict(os.environ, environment), patch.object(
        LLMClient, 'completions', return_value=content,
    ):
        cases = asyncio.run(_generate_with_llm(skill, full=True, fallback_to_template=False,
                                              announce_provider=False))
    return _to_agentskills_dataset(skill_name, cases)
