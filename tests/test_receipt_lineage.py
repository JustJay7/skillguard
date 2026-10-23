import json

import pytest

from skillguard.evaluation.receipt_learning import REFRESH_REPAIR
from skillguard.learning_report import repair_lineage
from skillguard.review.snapshot import digest


@pytest.mark.parametrize('fault', [None, 'gate', 'candidate', 'source', 'experiment', 'outside'])
def test_checked_holdout_binds_its_known_case_gate_and_frozen_sources(tmp_path, fault):
    root = tmp_path
    folder = root / 'results/integration/fresh'
    dev = root / 'results/integration/development'
    folder.mkdir(parents=True)
    dev.mkdir()
    experiment = dev / 'experiment.json'
    experiment.write_text('{"scope":"known fixture"}')
    gate = dev / 'development-gate.json'
    gate.write_text(json.dumps({'passed': True, 'known_case_development_only': True,
        'fresh_inputs_not_yet_authored': True, 'candidate_sha256': 'candidate',
        'experiment_sha256': digest(experiment.read_bytes())}))
    lineage = {'development_gate': str(gate), 'development_gate_sha256': digest(gate.read_bytes()),
        'manifest_sha256': 'manifest', 'fresh_cases_source_sha256': 'cases',
        'candidate_unchanged_from_gate': True}
    if fault == 'gate':
        gate.write_text(gate.read_text() + ' ')
    elif fault == 'candidate':
        lineage['candidate_unchanged_from_gate'] = False
    elif fault == 'source':
        lineage['fresh_cases_source_sha256'] = 'changed'
    elif fault == 'experiment':
        experiment.write_text('{}')
    elif fault == 'outside':
        lineage['development_gate'] = str(root / 'outside.json')
    (folder / 'evaluation-lineage.json').write_text(json.dumps(lineage))
    manifest = {'protocol': REFRESH_REPAIR, 'candidate_sha256': 'candidate'}
    state = {'manifest_sha256': 'manifest', 'runtime_identity': {
        'skillguard/evaluation/receipt_refresh_cases.py': 'cases'}}
    if fault:
        with pytest.raises(ValueError):
            repair_lineage(root, folder, manifest, state)
    else:
        assert set(repair_lineage(root, folder, manifest, state)) == {
            'evaluation-lineage.json', 'development-gate.json'}
