import os

import pytest

os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')

from harbor.agents.terminus_2 import Terminus2  # noqa: E402

from scripts.native_harbor_compat import frontmatter_compat  # noqa: E402


def test_compatibility_delegates_to_pinned_native_parser_and_restores_it():
    content = '--- \nname: receipt-organizer\ndescription: Fictional skill.\n---\nBody.'
    original = Terminus2._parse_skill_frontmatter
    assert original(content) is None
    with frontmatter_compat(True) as proof:
        assert Terminus2._parse_skill_frontmatter(content) == {
            'name': 'receipt-organizer', 'description': 'Fictional skill.'}
        assert proof['harbor_version'] == '0.13.2'
        assert content.startswith('--- \n')
    assert Terminus2._parse_skill_frontmatter is original


def test_compatibility_does_not_accept_missing_frontmatter_or_invalid_yaml():
    with frontmatter_compat(True):
        for content in ('name: fake', '--- \nname: [\n---\n', '--- \nname: fake\n---\n'):
            assert Terminus2._parse_skill_frontmatter(content) is None


def test_native_parser_is_restored_after_failure():
    original = Terminus2._parse_skill_frontmatter
    with pytest.raises(RuntimeError), frontmatter_compat(True):
        raise RuntimeError('offline diagnostic failure')
    assert Terminus2._parse_skill_frontmatter is original
