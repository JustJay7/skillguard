"""Bind region reconstruction to a retained native capture and its known fixture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore
from skillguard.traces.mapping_regions import analyze_mapping_regions


def analyze_capture(folder: Path) -> tuple[dict, dict[str, bytes]]:
    backend = json.loads((folder / 'backend.json').read_text())
    if (backend.get('error') or backend.get('fixed_probe_passed') is not True
            or backend.get('runner_stopped') is not True
            or backend.get('capture_startup') is not True
            or backend.get('complete') is not False or backend.get('model_calls') != 0):
        raise ValueError('Mapping analysis needs a healthy bounded startup capture')
    names = ('workload.jsonl', 'probe-console.json')
    artifacts = {name: (folder / name).read_bytes() for name in names}
    if any(digest(raw) != backend['artifacts'].get(name) for name, raw in artifacts.items()):
        raise ValueError('Native mapping source artifact changed')
    probe = json.loads(artifacts['probe-console.json'])
    fixture = probe['workload_checks']['mapping_lifecycle_checks']
    analysis = analyze_mapping_regions(artifacts['workload.jsonl'].decode(),
        container_id=backend['container_id'], page_size=fixture['page_size'])
    expected = '/sandbox/fixed-trace-probe/mapped-upgrade.txt'
    changes = [c for c in analysis['changes'] if c['start'] == int(fixture['address'], 16)
        and c['end'] - c['start'] == fixture['page_size']
        and len(c['backing_ranges']) == 1 and c['backing_ranges'][0]['path'] == expected]
    if (len(changes) != 2 or [c['kind'] for c in changes] != ['mprotect', 'munmap']
            or changes[0]['protection'] != 'PROT_READ|PROT_WRITE'
            or expected not in analysis['mapping_capabilities']['files_written']
            or fixture['mprotect_returncode'] != 0 or fixture['munmap_returncode'] != 0
            or fixture['shared_source_changed'] is not True
            or fixture['failed_mprotect_returncode'] != -1):
        raise ValueError('Native fixed mapping lifecycle does not match reconstructed ranges')
    report = {'source_run': backend['run_id'], 'container_id': backend['container_id'],
        'candidate_sha256': backend['candidate_execution']['candidate_sha256'],
        'scope': 'Bounded native mapping-region reconstruction; no page/inode access proof',
        'fixed_lifecycle_passed': True, 'complete': False, 'activation_permitted': False,
        'model_calls': 0, 'page_size_source': 'Known fixed workload sysconf(_SC_PAGE_SIZE)',
        'analysis': analysis, 'fixed_changes': changes}
    artifacts['backend.json'] = (folder / 'backend.json').read_bytes()
    report['artifacts'] = {k: digest(v) for k, v in artifacts.items()}
    return report, artifacts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = args.folder.resolve()
    report, artifacts = analyze_capture(folder)
    backend = json.loads(artifacts['backend.json'])
    candidate = backend['candidate_execution']
    store = ReviewStore(Path(candidate['store']))
    event = store.record_mapping_region_analysis(candidate['review_id'],
        report=json.dumps(report).encode(), artifacts=artifacts)
    report['stored_analysis'] = event['data']
    report['decision'] = store.decide(candidate['review_id'])
    (folder / 'mapping-regions.json').write_text(json.dumps(report, indent=2) + '\n')
    (root / 'results/mapping-regions-latest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'source_run': report['source_run'], 'fixed_lifecycle_passed': True,
        'observed_mappings': len(report['analysis']['mappings']),
        'resolved_changes': len(report['analysis']['changes']),
        'unresolved_events': len(report['analysis']['unresolved_events']),
        'complete': False, 'activation_permitted': False}, indent=2))


if __name__ == '__main__':
    main()
