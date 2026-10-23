"""Recover only the saved regular answer; preserve failed native export and all claims."""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.run_native_evaluation import PREFIX
from skillguard.evaluation.receipt_output_recovery import answer_from_archive, checked_answer
from skillguard.review.snapshot import digest

GUEST = '''import base64,json,subprocess,sys
cid,image=sys.argv[1:]
def inspect():
 c=json.loads(subprocess.check_output(['docker','inspect',cid]))[0]
 assert c['Id']==cid and c['Image']==image and c['State']['Running'] is False
 return {'container_id':c['Id'],'image_id':c['Image'],'running':c['State']['Running'],
         'finished_at':c['State']['FinishedAt']}
before=inspect()
raw=subprocess.check_output(['docker','cp',cid+':/workspace/out','-'])
assert len(raw)<=16*1024**2
after=inspect();assert before==after
print(json.dumps({'archive':base64.b64encode(raw).decode(),
 'container_before':before,'container_after':after}))
'''


def recover(root: Path, folder: Path) -> dict:
    folder = folder.resolve()
    if not folder.is_relative_to(root / 'results/integration'):
        raise ValueError('A local native run is required')
    report_raw = (folder / 'report.json').read_bytes()
    report = json.loads(report_raw)
    trial = Path(report['native_trial']).parent
    manifest = json.loads((trial / 'artifacts/manifest.json').read_text())
    if not any(a['source'] == '/workspace/out' and a['status'] == 'failed' for a in manifest):
        raise ValueError('Only a failed native output export may recover')
    binding = json.loads((trial / 'environment/openshell/binding.json').read_text())
    cid, image = binding['container_id'], binding['image_id']
    if not re.fullmatch('[0-9a-f]{64}', cid) or not re.fullmatch('sha256:[0-9a-f]{64}', image):
        raise ValueError('Full native container/image identity required')
    recovery = folder / 'output-recovery'
    recovery.mkdir(mode=0o700)
    (recovery / 'original-report.json').write_bytes(report_raw)
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG') if k in os.environ}
    env['LIMA_HOME'] = str(root.parent / 'work/lr')
    with (root.parent / 'work/lr/core-operation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            result = subprocess.run(['limactl', 'start', '--yes', '--timeout', '90s',
                'sgtrace-clean'], env=env, capture_output=True, timeout=120)
            (recovery / 'vm-start.txt').write_bytes(result.stdout + result.stderr)
            result.check_returncode()
            result = subprocess.run(PREFIX + ['python3', '-c', GUEST, cid, image],
                env=env, capture_output=True, timeout=60, check=True)
            data = json.loads(result.stdout)
            raw = base64.b64decode(data.pop('archive'), validate=True)
            answer, inventory = answer_from_archive(raw)
            (recovery / 'out.tar').write_bytes(raw)
            proof = {**data, 'source': '/workspace/out',
                'recorded_utc': datetime.now(UTC).isoformat(),
                'agent_or_model_execution': False, 'original_report_sha256': digest(report_raw),
                'archive_sha256': digest(raw), 'answer_sha256': digest(answer),
                'inventory': inventory, 'method': 'docker cp from the bound stopped container; '
                    'only a regular answer is read; links are retained as metadata, never followed'}
            proof_raw = (json.dumps(proof, indent=2) + '\n').encode()
            (recovery / 'proof.json').write_bytes(proof_raw)
            report['answer_export_recovery'] = {'proof_sha256': digest(proof_raw),
                'archive_sha256': digest(raw), 'original_report_sha256': digest(report_raw)}
            checked, _ = checked_answer(folder, report)
            target = trial / 'artifacts/out/answer.json'
            if target.exists() or target.is_symlink():
                raise ValueError('Never overwrite an existing output artifact')
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(checked)
            (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            return proof
        finally:
            result = subprocess.run(['limactl', 'stop', 'sgtrace-clean'], env=env,
                                    capture_output=True, timeout=90)
            (recovery / 'vm-stop.txt').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                subprocess.run(['limactl', 'stop', '--force', 'sgtrace-clean'], env=env,
                               capture_output=True, timeout=60, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    value = recover(Path(__file__).resolve().parents[1], args.folder)
    print(json.dumps({k: value[k] for k in ('source', 'answer_sha256',
                                         'agent_or_model_execution', 'inventory')}, indent=2))
