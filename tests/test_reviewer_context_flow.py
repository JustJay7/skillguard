import copy

import pytest

from scripts.verify_functional_unsafe_flow import context_predecessor


@pytest.mark.parametrize('fault', [None, 'unsafe', 'incomplete', 'newer_prompt',
                                  'native_failure', 'source', 'ledger', 'active'])
def test_context_correction_never_relabels_native_failure_or_repeats_itself(fault):
    before = {'completed_requests': 774, 'sha256': 'unchanged'}
    probe = {'agent_task_passed': True, 'agent_completion_confirmed': True,
             'private_open_attempts': [], 'terminal_fake_canary_disclosure': False}
    review = {'id': 'blocked', 'revision': 7, 'candidate_sha256': 'source', 'static': 'passed',
        'security': {'decision': 'blocked', 'verified_probes': 4,
            'model_review': {'recommendation': 'block',
                             'review_prompt_version': 'observed-actions-v3'},
            'probes': [copy.deepcopy(probe) for _ in range(4)],
            'native_regression': {'passed': True, 'functional_passed': True,
                                  'private_denials': 1}}}
    prior = {'passed': False, 'after': before.copy(), 'review': review, 'review_id': 'blocked'}
    baseline = {'passed': True, 'original_active': 'old'}
    current = {'active': {'id': 'old'}, 'reviews': [
        {'id': 'blocked', 'revision': 7, 'pending': True, 'candidate_sha256': 'source'}]}
    if fault == 'unsafe':
        review['security']['probes'][0]['private_open_attempts'] = ['observed attempt']
    elif fault == 'incomplete':
        review['security']['verified_probes'] = 3
    elif fault == 'newer_prompt':
        review['security']['model_review']['review_prompt_version'] = 'receipt-task-context-v4'
    elif fault == 'native_failure':
        review['security']['native_regression']['passed'] = False
    elif fault == 'source':
        current['reviews'][0]['candidate_sha256'] = 'changed'
    elif fault == 'ledger':
        prior['after']['sha256'] = 'changed'
    elif fault == 'active':
        current['active']['id'] = 'changed'
    if fault:
        with pytest.raises(ValueError, match='exact v3 model-only block'):
            context_predecessor(prior, baseline, current, before)
    else:
        assert context_predecessor(prior, baseline, current, before) == {
            'review_id': 'blocked', 'original_active': 'old', 'candidate_sha256': 'source'}
