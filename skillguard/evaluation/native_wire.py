"""Delegate response normalization to the same source-pinned native Harbor parser."""
from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
from functools import lru_cache

PARSER_SHA256 = 'd33fec0a5c6864375397e6b627f742cac0e16d7037708730926bd27ab29a4925'


@lru_cache(maxsize=1)
def parser():
    from harbor.agents.terminus_2.terminus_json_plain_parser import TerminusJSONPlainParser

    if (importlib.metadata.version('harbor') != '0.13.2' or hashlib.sha256(
            inspect.getsource(TerminusJSONPlainParser).encode()).hexdigest() != PARSER_SHA256):
        raise ValueError('Native wire-parser source/version differs')
    return TerminusJSONPlainParser()


def signature(raw: str) -> tuple[tuple[list, bool], str]:
    result = parser().parse_response(raw)
    if result.error:
        return ([], False), result.error
    commands = [{'keystrokes': c.keystrokes, 'duration': c.duration} for c in result.commands]
    return (commands, bool(result.is_task_complete)), ''


def rejection_corroborated(raw: str, error: str, steps: list) -> bool:
    from skillguard.evaluation.native_commands import step_signature

    return bool(error) and any(s.get('message') == raw and step_signature(s) == ([], False)
        and any('Previous response had parsing errors:\nERROR: ' + error in o.get('content', '')
                for o in s.get('observation', {}).get('results', [])) for s in steps)
