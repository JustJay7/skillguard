import json
from pathlib import Path

import pytest

from scripts.analyze_native_mapping_regions import analyze_capture
from skillguard.review.snapshot import digest
from tests.test_metadata_policy_evidence import source_fixture


def fixture(tmp_path):
    store, rid, _ = source_fixture(tmp_path)
    candidate = store.get(rid)['candidate_sha256']
    source_dir = Path(__file__).parent / 'fixtures'
    source = json.loads((source_dir / 'sysdig-native-mapping-changes-source.json').read_text())
    capture = tmp_path / 'native-fixture'
    capture.mkdir()
    artifacts = {'workload.jsonl': (
        source_dir / 'sysdig-native-mapping-changes.jsonl').read_bytes(),
        'probe-console.json': json.dumps({'workload_checks': {'mapping_lifecycle_checks': {
            'page_size': 4096, 'address': 'FFFF963DB000', 'mprotect_returncode': 0,
            'munmap_returncode': 0, 'shared_source_changed': True,
            'failed_mprotect_returncode': -1}}}).encode()}
    backend = {'run_id': 'offline-native-fixture', 'container_id': source['container_id'],
        'fixed_probe_passed': True, 'capture_startup': True, 'runner_stopped': True,
        'complete': False, 'model_calls': 0, 'candidate_execution': {
            'candidate_sha256': candidate, 'source_hashes_match': True, 'functional_passed': True,
            'image_id': 'sha256:offline-fixture'},
        'artifacts': {k: digest(v) for k, v in artifacts.items()}}
    store._append(rid, 'candidate_execution', {  # Offline binding fixture only.
        'candidate_sha256': candidate, 'image_id': 'sha256:offline-fixture', 'failure_reasons': [],
        'complete': False, 'functional_passed': True,
        'scope': 'Offline native binding fixture', 'mismatched_fields': [], 'event_references': {},
        'attachments': store._archive_attachments(rid, artifacts)})
    artifacts['backend.json'] = json.dumps(backend).encode()
    for name, raw in artifacts.items():
        (capture / name).write_bytes(raw)
    report, _ = analyze_capture(capture)
    return store, rid, report, artifacts


def record(store, rid, report, artifacts):
    report['artifacts'] = {k: digest(v) for k, v in artifacts.items()}
    return store.record_mapping_region_analysis(rid, report=json.dumps(report).encode(),
                                                artifacts=artifacts)


def test_native_region_evidence_is_separate_and_cannot_activate(tmp_path):
    store, rid, report, artifacts = fixture(tmp_path)
    event = record(store, rid, report, artifacts)
    assert event['data']['resolved_changes'] == 2
    assert event['data']['complete'] is False
    assert store.evidence(rid)['E15']['kind'] == 'bounded_native_mapping_region_analysis'
    assert store.decide(rid)['activation_permitted'] is False


@pytest.mark.parametrize('fault', ['candidate', 'complete', 'activation', 'claims', 'page_size',
    'events', 'source_hash', 'capture_loss', 'stopped', 'fixture', 'paid', 'latest_native'])
def test_native_region_proof_rejects_forged_or_promoted_analysis(tmp_path, fault):
    store, rid, report, artifacts = fixture(tmp_path)
    if fault in ('candidate', 'complete', 'activation'):
        report[{'candidate': 'candidate_sha256', 'complete': 'complete',
                'activation': 'activation_permitted'}[fault]] = True
    elif fault == 'claims':
        report['analysis']['mapping_capabilities']['files_written'].append('/real/not-observed')
    elif fault == 'latest_native':
        store._append(rid, 'candidate_execution', {'candidate_sha256': report['candidate_sha256'],
            'image_id': 'sha256:offline-fixture', 'failure_reasons': [], 'attachments': []})
    else:
        label = ('probe-console.json' if fault in ('page_size', 'fixture') else
                 'workload.jsonl' if fault == 'events' else 'backend.json')
        if fault == 'events':
            artifacts[label] = b'{}\n'
        else:
            value = json.loads(artifacts[label])
            if fault == 'page_size':
                value['workload_checks']['mapping_lifecycle_checks']['page_size'] = 8192
            elif fault == 'fixture':
                value['workload_checks']['mapping_lifecycle_checks'][
                    'shared_source_changed'] = False
            elif fault == 'source_hash':
                value['candidate_execution']['source_hashes_match'] = False
            elif fault == 'capture_loss':
                value['fixed_probe_passed'] = False
            elif fault == 'stopped':
                value['runner_stopped'] = False
            elif fault == 'paid':
                value['model_calls'] = 1
            artifacts[label] = json.dumps(value).encode()
    with pytest.raises(ValueError):
        record(store, rid, report, artifacts)
