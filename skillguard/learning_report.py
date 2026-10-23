"""Checked, read-only presentation of a completed native skill comparison."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from skillguard.review.snapshot import artifact_tree_digest, digest
from skillguard.review.store import ReviewStore


def repair_lineage(root: Path, folder: Path, manifest: dict, state: dict) -> dict[str, bytes]:
    """Retain local development-to-holdout provenance with the checked result."""
    from skillguard.evaluation.receipt_learning import REFRESH_REPAIR

    if manifest['protocol'] != REFRESH_REPAIR:
        return {}
    raw = (folder / 'evaluation-lineage.json').read_bytes()
    lineage = json.loads(raw)
    gate_path = Path(lineage['development_gate']).resolve()
    if not gate_path.is_relative_to((root / 'results/integration').resolve()):
        raise ValueError('Development provenance must remain local')
    gate_raw = gate_path.read_bytes()
    gate = json.loads(gate_raw)
    if (lineage['development_gate_sha256'] != digest(gate_raw)
            or lineage['manifest_sha256'] != state['manifest_sha256']
            or lineage['fresh_cases_source_sha256'] != state['runtime_identity'][
                'skillguard/evaluation/receipt_refresh_cases.py']
            or lineage.get('candidate_unchanged_from_gate') is not True
            or gate.get('passed') is not True
            or gate.get('known_case_development_only') is not True
            or gate.get('fresh_inputs_not_yet_authored') is not True
            or gate['candidate_sha256'] != manifest['candidate_sha256']
            or gate['experiment_sha256'] != digest(
                (gate_path.parent / 'experiment.json').read_bytes())):
        raise ValueError('Development-to-holdout provenance changed')
    return {'evaluation-lineage.json': raw, 'development-gate.json': gate_raw}


def archive(root: Path, experiment: Path) -> dict:
    from scripts.receipt_learning_workflow import summarize
    from scripts.verify_receipt_learning import verify
    from skillguard.evaluation.receipt_learning import selected_candidate

    experiment = experiment.resolve()
    if not experiment.is_relative_to((root / 'results/integration').resolve()):
        raise ValueError('A local project comparison is required')
    state = json.loads(experiment.read_text())
    folder = experiment.parent
    manifest_raw = (folder / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get('development_only'):
        raise ValueError('Development checks are not a paired learning comparison')
    if (state['status'] != 'completed' or not state['summary']['complete_matrix']
            or state['manifest_sha256'] != digest(manifest_raw)
            or len(state['results']) != len(manifest['trials'])):
        raise ValueError('A complete verified frozen matrix is required')
    if {r['trial_id'] for r in state['results']} != {t['id'] for t in manifest['trials']}:
        raise ValueError('Missing or duplicated paired trial identities')
    behavior_review = None
    if manifest.get('comparison_kind') == 'guide_repair':
        from skillguard.evaluation.receipt_command_audit import verify as verify_commands
        from skillguard.evaluation.receipt_learning import (
            REFRESH_REPAIR,
            REPAIR_PROTOCOL,
            SELECTED_REPAIR,
        )

        if manifest['protocol'] in {REPAIR_PROTOCOL, SELECTED_REPAIR, REFRESH_REPAIR}:
            freeze = Path(manifest['repair_source_freeze'])
            if digest(freeze.read_bytes()) != manifest['repair_source_freeze_sha256']:
                raise ValueError('Repair source freeze changed')
        behavior_review = verify_commands(folder, state['results'])
    attachments = {'manifest.json': manifest_raw, 'experiment.json': experiment.read_bytes(),
                   'native-collector.json': (folder / 'native-collector.json').read_bytes()}
    attachments.update(repair_lineage(root, folder, manifest, state))
    if (folder / 'verification-recovery.json').exists():
        attachments['verification-recovery.json'] = (folder /
            'verification-recovery.json').read_bytes()
    if behavior_review:
        attachments['repair-source-freeze.json'] = Path(
            manifest['repair_source_freeze']).read_bytes()
        attachments['command-audit.json'] = (folder / 'command-audit.json').read_bytes()
    for result in state['results']:
        run = root / 'results/integration' / result['run_id']
        if verify(root, run) != result:
            raise ValueError('Recomputed trial differs from the recorded comparison')
        attachments[result['trial_id'] + '-report.json'] = (run / 'report.json').read_bytes()
        recovered_report = json.loads((run / 'report.json').read_text())
        if recovered_report.get('answer_export_recovery'):
            from skillguard.evaluation.receipt_output_recovery import checked_answer

            _, recovered = checked_answer(run, recovered_report)
            attachments.update({result['trial_id'] + '-' + k: v for k, v in recovered.items()})
        trial = Path(result['native_trial']).parent
        copied = (folder / 'collected-jobs' /
                  ('receipt-organizer-terminus-2-' + result['arm']) /
                  (result['case_id'] + '__' + trial.name))
        if artifact_tree_digest(copied) != artifact_tree_digest(trial):
            raise ValueError('Native collector copy differs from original trial')
        attachments[result['trial_id'] + '-answer.json'] = (
            (trial / 'artifacts/out/answer.json').read_bytes()
            if (trial / 'artifacts/out/answer.json').exists() else b'null')
        attachments[result['trial_id'] + '-trajectory.json'] = (
            trial / 'agent/trajectory.json').read_bytes()
    recomputed = summarize(root, manifest, state['results'], folder)
    if recomputed != state['summary']:
        raise ValueError('Recomputed paired statistics differ from stored summary')
    attachments['native-collector.json'] = (folder / 'native-collector.json').read_bytes()
    candidate = selected_candidate(root, manifest, 'with')
    original = ReviewStore(Path(candidate['store'])).get(candidate['review_id'])
    store = ReviewStore(folder / 'checked-review')
    review_id = store.capture(Path(original['snapshot']).parent / 'pending.json')
    if store.get(review_id)['candidate_sha256'] != manifest['candidate_sha256']:
        raise ValueError('Archived comparison candidate differs')
    rows = list(csv.DictReader((root / 'results/cost_log.csv').open()))
    charges = [float(r['reserved_cost_usd'] or 0) + float(r['estimated_cost_usd'] or 0)
               for r in rows]
    if any(not math.isfinite(c) or c < 0 for c in charges) or sum(charges) > .75:
        raise ValueError('Shared ledger exceeds authorized cap or has invalid accounting')
    ledger = {'completed_requests': sum(r['status'] == 'completed' for r in rows),
              'estimated_cost_usd': sum(float(r['estimated_cost_usd'] or 0) for r in rows),
              'unknown_reserved_usd': sum(float(r['reserved_cost_usd'] or 0) for r in rows)}
    summary = state['summary']
    arms = {}
    for arm in ('with', 'without'):
        selected = [r for r in state['results'] if r['arm'] == arm]
        arms[arm] = {'model_requests': sum(r['model_requests'] for r in selected),
            'correct_saved_answers': sum(r['functional_passed'] for r in selected),
            'correct_confirmed_tasks': sum(r['task_passed'] for r in selected),
            'private_open_attempts': sum(len(r['private_open_attempts_during_agent'])
                                         for r in selected),
            'terminal_disclosures': sum(r['terminal_fake_canary_disclosure'] for r in selected),
            'guide_reads_observed': sum(bool(r['skill_use'].get('guide_read_observed'))
                                        for r in selected),
            'input_tokens': sum(r['input_tokens'] for r in selected),
            'output_tokens': sum(r['output_tokens'] for r in selected)}
        if manifest.get('skill_selection'):
            arms[arm]['guide_before_receipt_observed'] = sum(r.get('selected_skill_evidence',
                {}).get('guide_before_receipt_observed', False) for r in selected)
        if any('guide_after_receipt_observed' in r.get('selected_skill_evidence', {})
               for r in selected):
            arms[arm]['guide_after_receipt_observed'] = sum(r.get('selected_skill_evidence',
                {}).get('guide_after_receipt_observed', False) for r in selected)
    guarded = {}
    for group in ('all', 'clean', 'attack'):
        selected = state['results'] if group == 'all' else [
            r for r in state['results'] if r['group'] == group]
        guarded[group] = {arm: sum(r['guarded_task_passed'] for r in selected if r['arm'] == arm)
                          for arm in ('with', 'without')}
    view = {'run_id': manifest['run_id'], 'candidate_sha256': manifest['candidate_sha256'],
            'protocol': manifest['protocol'],
            'skill_selection': manifest.get('skill_selection'),
            'comparison_kind': manifest.get('comparison_kind', 'skill_access'),
            'arm_labels': manifest.get('arm_labels', {
                'with': 'With skill', 'without': 'Without skill'}),
            'arm_candidates': manifest.get('arm_candidates'),
            'behavior_review': behavior_review,
            'groups': summary['groups'], 'pairs': summary['pairs'], 'arms': arms,
            'guarded_passes': guarded,
            'ledger': ledger, 'model_requests': summary['model_requests'],
            'estimated_cost_usd': summary['estimated_cost_usd'],
            'cases': [{'id': c['id'], 'group': c['group'],
                       'vendor': c['contract']['expected']['receipt']['vendor'],
                       'attack_family': c.get('attack_family')} for c in manifest['cases']],
            'scope': summary['scope'], 'unrestricted_activation_permitted': False,
            'interpretation': state.get('interpretation', 'small_fixed_comparison'),
            'safety_finding': state.get('safety_finding'),
            'prior_study': state.get('prior_study'),
            'verified_trials': len(state['results']),
            'native_lift': json.loads(attachments['native-collector.json'])['custom_lift']}
    event = store._append(review_id, 'heldout_comparison', {
        **view, 'attachments': store._archive_attachments(review_id, attachments)})
    pointer = {'run_id': manifest['run_id'], 'store': str(store.root), 'review_id': review_id,
               'event_sha256': event['sha256']}
    (root / 'results/receipt-learning-review-latest.json').write_text(
        json.dumps(pointer, indent=2) + '\n')
    return view


def read(root: Path) -> dict | None:
    path = root / 'results/receipt-learning-review-latest.json'
    pointer = json.loads(path.read_text()) if path.exists() else None
    active = root / 'results/receipt-learning-active.json'
    if active.exists():
        ref = json.loads(active.read_text())
        manifest = Path(ref['manifest']).resolve()
        if (not manifest.is_relative_to((root / 'results/integration').resolve())
                or digest(manifest.read_bytes()) != ref['sha256']):
            raise ValueError('Active comparison descriptor changed')
        state_path = manifest.parent / 'experiment.json'
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if (state['status'] != 'completed' or not pointer
                    or pointer.get('run_id') != state['run_id']):
                status = state['status'] if state['status'] != 'completed' else 'verifying'
                return {'status': status,
                        'recorded_trials': len(state['results']),
                        'planned_trials': len(json.loads(manifest.read_text())['trials'])}
    if pointer is None:
        return None
    store_path = Path(pointer['store']).resolve()
    if not store_path.is_relative_to((root / 'results/integration').resolve()):
        raise ValueError('Comparison archive must remain local')
    review = ReviewStore(store_path).get(pointer['review_id'])
    event = next(e for e in reversed(review['history']) if e['kind'] == 'heldout_comparison')
    if (event['sha256'] != pointer['event_sha256']
            or event['data']['candidate_sha256'] != review['candidate_sha256']):
        raise ValueError('Comparison archive changed')
    return {'status': 'completed',
            **{k: v for k, v in event['data'].items() if k != 'attachments'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(archive(Path(__file__).resolve().parents[1], args.experiment), indent=2))
