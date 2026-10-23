import json

import pytest


def test_single_candidate_development_never_computes_or_presents_skill_lift(tmp_path, monkeypatch):
    pytest.importorskip('skillevaluator')
    from skillevaluator.tier3.harbor import collector, metrics

    from scripts.receipt_learning_workflow import summarize

    source = tmp_path / 'trial'
    source.mkdir()
    (source / 'result.json').write_text('{}')
    monkeypatch.setattr(collector, '_extract_rewards', lambda *args: [])
    monkeypatch.setattr(metrics, 'average_custom_metrics', lambda *args: {'overall': 1})
    monkeypatch.setattr(collector, '_condition_execution_summary', lambda *args, **kwargs: {
        'execution_status': 'succeeded'})
    monkeypatch.setattr(collector, '_compute_custom_lift', lambda *args, **kwargs: pytest.fail(
        'No improvement score can be computed without a control'))
    manifest = {'development_only': True, 'cases': [
        {'id': 'd01', 'group': 'attack', 'native_case_id': 'fixture-d01'}],
        'trials': [{'id': 'd01-with'}]}
    results = [{'trial_id': 'd01-with', 'case_id': 'd01', 'arm': 'with', 'verified': True,
        'native_trial': str(source / 'result.json'), 'model_requests': 5,
        'estimated_cost_usd': .001}]
    folder = tmp_path / 'experiment'
    folder.mkdir()
    result = summarize(tmp_path, manifest, results, folder)
    assert result['complete_matrix'] and result['paired_comparison'] is False
    assert 'groups' not in result
    native = json.loads((folder / 'native-collector.json').read_text())
    assert native['custom_lift'] is None and set(native['conditions']) == {'with'}


def test_development_cannot_be_archived_as_a_paired_learning_result(tmp_path):
    from skillguard.learning_report import archive

    folder = tmp_path / 'results/integration/development'
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text('{"development_only":true}')
    path = folder / 'experiment.json'
    path.write_text('{}')
    with pytest.raises(ValueError, match='not a paired learning comparison'):
        archive(tmp_path, path)
    assert not (tmp_path / 'results/receipt-learning-review-latest.json').exists()
