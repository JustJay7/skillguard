"""Run NVIDIA Harbor's Oracle and verifier inside native OpenShell; no inference."""
from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import tarfile
import traceback
from pathlib import Path

from scripts.native_agent_capture import NativeAgentCapture
from scripts.native_receipt_controller import FAKE_KEY, confinement
from skillguard.review.snapshot import artifact_tree_digest
from skillguard.traces.sysdig import SYSDIG_FORMAT


async def execute(root: Path):
    from harbor.job import Job
    from harbor.models.job.config import JobConfig

    capture = NativeAgentCapture(root, SYSDIG_FORMAT, 'openshell', scoped_metadata=True)
    capture.start()
    try:
        config = JobConfig.model_validate({'job_name': 'core-receipt',
            'jobs_dir': str(root / 'jobs'), 'n_attempts': 1, 'n_concurrent_trials': 1,
            'quiet': True, 'retry': {'max_retries': 0},
            'environment': {'type': None,
                'import_path': 'scripts.core_openshell_environment:CoreOpenShellEnvironment',
                'delete': True, 'env': {}, 'kwargs': {'expected_environment_sha256':
                    artifact_tree_digest(root / 'task/environment')}},
            'agents': [{'name': 'oracle', 'env': {}}], 'tasks': [{'path': str(root / 'task')}],
            'artifacts': ['/workspace/out', '/workspace/skills/receipt-organizer']})
        job = await Job.create(config)

        async def started(event):
            bindings = list((root / 'jobs').rglob('openshell/binding.json'))
            if len(bindings) != 1:
                raise ValueError('One native sandbox binding required')
            binding = json.loads(bindings[0].read_text())
            container = json.loads(subprocess.check_output(
                ['docker', 'inspect', binding['container_id']]))[0]
            capture.container_id = container['Id']
            proof = confinement(container, root, FAKE_KEY, binding['sandbox'])
            (root / 'container.json').write_text(json.dumps(container))
            (root / 'confinement.json').write_text(json.dumps(proof))
            if not proof['passed']:
                raise ValueError('Native sandbox confinement failed')

        job.on_agent_started(started)
        result = await job.run()
        (root / 'job-summary.json').write_text(result.model_dump_json())
    finally:
        capture.finish()


def main():
    root = Path(sys.argv[1])
    root.mkdir(mode=0o700)
    with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as archive:
        archive.extractall(root, filter='data')
    result = {'model_requests': 0}
    with (root / 'controller-log.txt').open('w') as log, contextlib.redirect_stdout(log), (
            contextlib.redirect_stderr(log)):
        try:
            asyncio.run(execute(root))
        except Exception:
            result['error'] = traceback.format_exc()
    (root / 'controller-result.json').write_text(json.dumps(result))
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
        for name in ('jobs', 'confinement.json', 'container.json',
                     'controller-result.json', 'controller-log.txt', 'job-summary.json'):
            if (root / name).exists():
                archive.add(root / name, arcname=name)
        # Keep the full compressed native capture in the dedicated VM. Export
        # only checked metadata; this app never claims complete runtime evidence.
        for name in ('capture.json', 'events.jsonl', 'stats.txt'):
            path = root / 'capture' / name
            if path.exists():
                archive.add(path, arcname='capture/' + name)


if __name__ == '__main__':
    main()
