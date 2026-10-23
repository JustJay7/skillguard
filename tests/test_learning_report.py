import json
from pathlib import Path

import pytest

from skillguard.core import CoreWorkspace
from skillguard.learning_report import read
from skillguard.review.store import ReviewStore
from tests.test_core import candidate


@pytest.mark.parametrize('fault', [None, 'artifact', 'candidate'])
def test_comparison_view_requires_a_hash_checked_candidate_bound_archive(tmp_path, fault):
    root = tmp_path / 'repo'
    root.mkdir()
    w = CoreWorkspace(root, root / 'results/integration/comparison')
    rid = candidate(w)
    store = ReviewStore(w.store.root)
    event = store._append(rid, 'heldout_comparison', {
        'candidate_sha256': (store.get(rid)['candidate_sha256']
                             if fault != 'candidate' else 'changed'),
        'scope': 'Offline integrity fixture, not a live result'})
    pointer = {'store': str(store.root), 'review_id': rid, 'event_sha256': event['sha256']}
    (root / 'results/receipt-learning-review-latest.json').write_text(json.dumps(pointer))
    if fault == 'artifact':
        Path(event['artifact']).write_text('{}')
    if fault:
        with pytest.raises(ValueError):
            read(root)
    else:
        assert read(root)['scope'] == 'Offline integrity fixture, not a live result'


def test_partial_matrix_cannot_be_published_as_a_completed_comparison(tmp_path):
    from skillguard.learning_report import archive
    from skillguard.review.snapshot import digest

    folder = tmp_path / 'results/integration/partial'
    folder.mkdir(parents=True)
    manifest = folder / 'manifest.json'
    manifest.write_text('{"trials":[{},{}]}')
    state = {'status': 'completed', 'manifest_sha256': digest(manifest.read_bytes()),
             'summary': {'complete_matrix': True}, 'results': [{}]}
    path = folder / 'experiment.json'
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='complete verified frozen matrix'):
        archive(tmp_path, path)
    assert not (tmp_path / 'results/receipt-learning-review-latest.json').exists()


@pytest.mark.parametrize('status', ['running', 'completed'])
def test_unarchived_progress_cannot_appear_as_verified_results(tmp_path, status):
    from skillguard.review.snapshot import digest

    folder = tmp_path / 'results/integration/current'
    folder.mkdir(parents=True)
    manifest = folder / 'manifest.json'
    manifest.write_text('{"trials":[{},{}]}')
    (tmp_path / 'results/receipt-learning-active.json').write_text(json.dumps({
        'manifest': str(manifest), 'sha256': digest(manifest.read_bytes())}))
    (folder / 'experiment.json').write_text(json.dumps({'run_id': 'fixture',
        'status': status, 'results': [{}]}))
    value = read(tmp_path)
    assert value == {'status': 'running' if status == 'running' else 'verifying',
                     'recorded_trials': 1, 'planned_trials': 2}
    assert 'groups' not in value
