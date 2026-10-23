from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import inspect
import re

NATIVE_PARSER_SHA256 = '204188b1cf9a004492f7b9e7c357c354eec7ed93eee766e3fec9bcb151b91fcc'


@contextlib.contextmanager
def frontmatter_compat(enabled: bool):
    if not enabled:
        yield {}
        return
    from harbor.agents.terminus_2 import Terminus2

    original = Terminus2._parse_skill_frontmatter
    actual = hashlib.sha256(inspect.getsource(original).encode()).hexdigest()
    if importlib.metadata.version('harbor') != '0.13.2' or actual != NATIVE_PARSER_SHA256:
        raise ValueError('Native frontmatter compatibility source differs from reviewed pin')

    def parse(content):
        normalized = re.sub(r'\A---[ \t]+\r?\n', '---\n', content, count=1)
        return original(normalized)

    Terminus2._parse_skill_frontmatter = staticmethod(parse)
    try:
        yield {'harbor_version': '0.13.2', 'native_parser_sha256': actual,
               'scope': 'Trailing whitespace on opening frontmatter delimiter only; '
                        'original selected guide bytes and native YAML parser retained'}
    finally:
        Terminus2._parse_skill_frontmatter = staticmethod(original)
