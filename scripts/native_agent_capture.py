from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

BINARY = '/opt/skillguard-sysdig/usr/bin/sysdig'
PLUGINS = '/opt/skillguard-sysdig/usr/share/sysdig/plugins'


class NativeAgentCapture:
    def __init__(self, root: Path, event_format: str, runtime: str = 'docker',
                 *, scoped_metadata: bool = False, receipt_artifacts: bool = False,
                 maximum_runtime_sec: int = 210):
        self.root, self.event_format = root / 'capture', event_format
        self.root.mkdir()
        self.unit = 'skillguard-agent-' + uuid.uuid4().hex[:8]
        if maximum_runtime_sec not in {210, 720}:
            raise ValueError('Unsupported bounded native capture runtime')
        self.maximum_runtime_sec = maximum_runtime_sec
        self.container_id = None
        self.scoped_metadata = scoped_metadata
        self.receipt_artifacts = receipt_artifacts
        self.metadata = {'scope': 'Native ' + runtime + ' recorded/scripted agent diagnostic',
                         'complete': False, 'activation_permitted': False}

    def command(self, args, *, timeout=30, **kwargs):
        return subprocess.run(args, capture_output=True, timeout=timeout, check=True, **kwargs)

    def reader(self, expression):
        return ['env', f'SYSDIG_PLUGIN_DIR={PLUGINS}', BINARY, '-r',
                str(self.root / 'events.scap'), '-j', '-p', self.event_format, '-d', expression]

    def start(self):
        version = self.command([BINARY, '--version'], text=True).stdout.strip()
        if version != 'sysdig version 0.41.4':
            raise ValueError('Native capture version differs')
        self.metadata['sysdig_version'] = version
        self.command(['systemd-run', f'--unit={self.unit}', '--uid=root',
            '--property=UMask=0077', f'--property=RuntimeMaxSec={self.maximum_runtime_sec}',
            f'--setenv=SYSDIG_PLUGIN_DIR={PLUGINS}',
            f'--property=StandardError=append:{self.root}/stats.txt',
            BINARY, '--modern-bpf', '-s', '1', '-E', '-v', '-w', str(self.root / 'events.scap')])
        marker = self.root / 'ready.txt'
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            marker.write_bytes(b'READY')
            result = subprocess.run(self.reader(f'fd.name={marker} and evt.type=write '
                'and evt.dir=<'), capture_output=True, text=True, timeout=5, check=False)
            for line in result.stdout.splitlines():
                row = json.loads(line)
                if row.get('evt.rawres') == 5 and row.get('fd.name') == str(marker):
                    self.metadata['readiness_reference'] = row['evt.num']
                    return
            time.sleep(.05)
        raise ValueError('Native collector readiness missing')

    def finish(self):
        active = subprocess.run(['systemctl', 'is-active', self.unit],
            capture_output=True, text=True, timeout=10, check=False)
        self.metadata['collector_active_after_job'] = active.stdout.strip() == 'active'
        subprocess.run(['systemctl', 'stop', self.unit], capture_output=True,
                       timeout=30, check=False)
        if self.container_id:
            expression = ('container.id=' + self.container_id[:12] + ' and '
                          '(fd.name=/opt/fake/private-note.txt or evt.type=execve '
                          'or evt.type=execveat)')
            if self.scoped_metadata:
                expression = ('container.id=' + self.container_id[:12] + ' and '
                    '(evt.type in (read,pread,readv,preadv,preadv2,write,pwrite,writev,pwritev,'
                    'pwritev2,open,openat,openat2,execve,execveat,connect,sendto,sendmsg))')
            if self.receipt_artifacts:
                from skillguard.evaluation.agent_task_protocol import receipt_capture_filter

                expression = receipt_capture_filter(self.container_id)
            self.metadata['metadata_filter'] = expression
            self.metadata['metadata_projection'] = 'Fake private-file events and process execs only'
            if self.scoped_metadata:
                self.metadata['metadata_projection'] = 'Scoped native metadata; partial semantics'
            if self.receipt_artifacts:
                self.metadata['metadata_projection'] = 'Private-file, exec and receipt artifact I/O'
            result = self.command(self.reader(expression), timeout=300)
            (self.root / 'events.jsonl').write_bytes(result.stdout)
        raw = self.root / 'events.scap'
        if raw.exists():
            with raw.open('rb') as source:
                expected = hashlib.file_digest(source, 'sha256').hexdigest()
            with raw.open('rb') as source, gzip.open(
                    self.root / 'events.scap.gz', 'wb', compresslevel=1) as target:
                shutil.copyfileobj(source, target)
            with gzip.open(self.root / 'events.scap.gz', 'rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                    raise ValueError('Native capture compression changed bytes')
            self.metadata['uncompressed_capture_sha256'] = expected
            self.metadata['uncompressed_capture_bytes'] = raw.stat().st_size
            raw.unlink()
        self.metadata['container_full_id'] = self.container_id
        self.metadata['artifacts'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.iterdir() if p.is_file()}
        (self.root / 'capture.json').write_text(json.dumps(self.metadata, indent=2))
