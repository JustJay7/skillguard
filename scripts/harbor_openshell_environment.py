from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import shlex
import signal
import tarfile
import uuid
from pathlib import Path, PurePosixPath

from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.environments.capabilities import EnvironmentCapabilities
from harbor.models.task.config import NetworkMode

from skillguard.review.snapshot import artifact_tree_digest

POLICY = '''version: 1
filesystem_policy:
  include_workdir: false
  read_only: [/bin, /usr, /lib, /lib64, /etc, /proc, /dev/urandom,
              /workspace/input, /workspace/skills]
  read_write: [/tmp, /dev/null, /dev/pts, /sandbox, /workspace/out, /logs, /tests]
landlock:
  compatibility: hard_requirement
process:
  run_as_user: "1000"
  run_as_group: "1000"
network_policies: {}
'''


class ReceiptOpenShellEnvironment(BaseEnvironment):
    def policy_text(self):
        return POLICY

    def __init__(self, *args, expected_environment_sha256: str, **kwargs):
        self.expected_environment_sha256 = expected_environment_sha256
        self.sandbox_name = 'sg-hb-' + uuid.uuid4().hex[:10]
        self.created = False
        super().__init__(*args, **kwargs)
        self._mounts = []
        self.adapter_root = self.trial_paths.trial_dir / 'environment/openshell'
        self.adapter_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def type():
        return 'skillguard-receipt-openshell'

    @property
    def capabilities(self):
        return EnvironmentCapabilities(disable_internet=True)

    def _validate_definition(self):
        if (not (self.environment_dir / 'Dockerfile').is_file()
                or (self.environment_dir / 'docker-compose.yaml').exists()
                or artifact_tree_digest(self.environment_dir) != self.expected_environment_sha256):
            raise ValueError('OpenShell requires the exact reviewed receipt environment')
        values = self._persistent_env
        harmless = all(value == '' or (name == 'CLAUDE_CODE_DISABLE_POLICY_SKILLS' and value == '1')
                       for name, value in values.items())
        if (values != (self.task_env_config.env or {}) or not harmless
                or self.task_env_config.docker_image):
            raise ValueError('Provider environment/prebuilt images are unsupported')
        for mount in self._mounts:
            target = mount.get('target') if isinstance(mount, dict) else mount.target
            source = mount.get('source') if isinstance(mount, dict) else mount.source
            if (target not in {'/logs/agent', '/logs/verifier', '/logs/artifacts'}
                    or not Path(source).resolve().is_relative_to(
                        self.trial_paths.trial_dir.resolve())):
                raise ValueError('Only native log requests are accepted; no mounts are forwarded')

    def _validate_network_policy_support(self):
        if self.network_policy.network_mode != NetworkMode.NO_NETWORK:
            raise ValueError('Receipt OpenShell profile requires no external network')

    def _reset_dirs_user(self):
        return '1000:1000'

    async def native(self, args, *, data: bytes | None = None, timeout=90, check=True):
        process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(data), timeout)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            drain_timed_out = False
            try:
                await asyncio.wait_for(process.communicate(), timeout=5)
            except TimeoutError:
                drain_timed_out = True
            # Never replace the timeout with a diagnostic-storage failure.
            with contextlib.suppress(OSError):
                (self.adapter_root / ('timeout-' + uuid.uuid4().hex[:8] + '.json')).write_text(
                    json.dumps({'command': args[0], 'timeout_seconds': timeout,
                        'owned_process_group': process.pid, 'group_kill_requested': True,
                        'cleanup_drain_timed_out': drain_timed_out}))
            raise
        if check and process.returncode:
            (self.adapter_root / ('error-' + uuid.uuid4().hex[:8] + '.txt')).write_bytes(
                stdout + stderr)
            raise RuntimeError('Native OpenShell adapter command failed: ' +
                               stderr.decode(errors='replace')[:500])
        return process.returncode, stdout, stderr

    async def start(self, force_build: bool):
        if artifact_tree_digest(self.environment_dir) != self.expected_environment_sha256:
            raise ValueError('Reviewed image input changed before native build')
        image = 'skillguard-harbor:' + self.sandbox_name
        _, stdout, stderr = await self.native(['env', 'DOCKER_BUILDKIT=0', 'docker', 'build',
            '-t', image, str(self.environment_dir)], timeout=300)
        (self.adapter_root / 'build.txt').write_bytes(stdout + stderr)
        _, raw, _ = await self.native(['docker', 'image', 'inspect', image])
        self.image_id = json.loads(raw)[0]['Id']
        policy = self.adapter_root / 'policy.yaml'
        policy.write_text(self.policy_text())
        # Mark before creation so a timeout still attempts native cleanup.
        self.created = True
        await self.native(['openshell', 'sandbox', 'create', '--name', self.sandbox_name,
            '--from', image, '--policy', str(policy), '--detach', '--no-auto-providers',
            '--', 'sleep', '3600'], timeout=120)
        _, raw, _ = await self.native(['openshell', 'sandbox', 'get', self.sandbox_name,
                                     '-o', 'json'])
        (self.adapter_root / 'sandbox.json').write_bytes(raw)
        _, raw, _ = await self.native(['docker', 'ps', '-q', '--filter',
                                       'label=openshell.ai/isolation-role=sandbox'])
        ids = raw.decode().split()
        _, raw, _ = await self.native(['docker', 'inspect', *ids])
        selected = [c for c in json.loads(raw) if c['Name'].startswith(
            '/openshell-default--' + self.sandbox_name + '-')]
        if len(selected) != 1 or selected[0]['Image'] != self.image_id:
            raise ValueError('OpenShell runtime image differs from reviewed build')
        (self.adapter_root / 'binding.json').write_text(json.dumps({
            'sandbox': self.sandbox_name, 'container_id': selected[0]['Id'],
            'image_id': self.image_id}, indent=2))
        probe = 'import json,os;print(json.dumps({"uid":os.getuid()}))'
        check = await self.exec('python3 -c ' + shlex.quote(probe))
        (self.adapter_root / 'effective-user.json').write_text(check.model_dump_json(indent=2))
        if check.return_code or json.loads(check.stdout)['uid'] != 1000:
            raise ValueError('OpenShell execution UID differs')

    async def stop(self, delete: bool):
        if not self.created:
            return
        _, raw, _ = await self.native(['openshell', 'sandbox', 'get', self.sandbox_name,
                                     '-o', 'json'])
        if json.loads(raw)['phase'] == 'Error':
            await self.native(['openshell', 'sandbox', 'delete', self.sandbox_name])
            (self.adapter_root / 'cleanup.json').write_text(json.dumps({
                'sandbox': self.sandbox_name, 'deleted_after_provisioning_error': True}))
            self.created = False
            return
        await self.native(['openshell', 'sandbox', 'stop', self.sandbox_name])
        _, raw, _ = await self.native(['openshell', 'sandbox', 'get', self.sandbox_name,
                                     '-o', 'json'])
        (self.adapter_root / 'stopped.json').write_bytes(raw)
        if json.loads(raw)['phase'] != 'Stopped':
            raise ValueError('Native OpenShell sandbox did not stop')
        self.created = False

    @staticmethod
    def checked_path(value):
        path = PurePosixPath(value)
        if not path.is_absolute() or '..' in path.parts or '\x00' in str(value):
            raise ValueError('Invalid native transfer path')
        return str(path)

    def command_args(self, command, cwd, env, timeout_sec, user):
        requested = self._resolve_user(user)
        unprivileged_check = command in ('tmux -V', 'chmod +x /tests/test.sh')
        if (requested not in (None, 1000, '1000', '1000:1000', 'sandbox')
                and not (requested == 'root' and unprivileged_check)):
            raise ValueError('Receipt profile never executes privileged commands')
        args = ['openshell', 'sandbox', 'exec', '--name', self.sandbox_name,
                '--no-tty', '--no-login-shell', '--timeout', str(timeout_sec or 60)]
        if cwd:
            args.extend(['--workdir', self.checked_path(cwd)])
        for name, value in (self._merge_env(env) or {}).items():
            if (not re.fullmatch(r'[A-Z_][A-Z0-9_]*', name) or
                    re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL', name)):
                raise ValueError('Secret/provider environment is unsupported')
            args.extend(['--env', name + '=' + value])
        return args + ['--', 'bash', '--noprofile', '--norc', '-c', command]

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        code, stdout, stderr = await self.native(
            self.command_args(command, cwd, env, timeout_sec, user),
            timeout=(timeout_sec or 60) + 15, check=False)
        result = ExecResult(return_code=code, stdout=stdout.decode(errors='replace'),
                            stderr=stderr.decode(errors='replace'))
        if command.startswith(('find /workspace/skills ', 'test -d /workspace/skills',
                                'cat /workspace/skills/receipt-organizer/SKILL.md')):
            path = self.adapter_root / 'discovery-checks.json'
            checks = json.loads(path.read_text()) if path.exists() else []
            checks.append({'command': command, **result.model_dump()})
            path.write_text(json.dumps(checks, indent=2))
        return result

    def transfer_args(self, command):
        return self.command_args(command, None, None, 60, '1000:1000')

    @staticmethod
    def upload_target(value):
        value = ReceiptOpenShellEnvironment.checked_path(value)
        if not any(value == p or value.startswith(p + '/') for p in ('/tests', '/logs', '/tmp')):
            raise ValueError('Native uploads may not alter the selected source or input')
        return value

    async def upload_file(self, source_path, target_path):
        target = self.upload_target(target_path)
        source = self.upload_source(source_path)
        if source.is_symlink() or source.stat().st_size > 4 * 1024**2:
            raise ValueError('Native file upload exceeds its scope')
        code = ('import pathlib,sys;p=pathlib.Path(' + repr(target) +
                ');p.parent.mkdir(parents=True,exist_ok=True);'
                'p.write_bytes(sys.stdin.buffer.read())')
        await self.native(self.transfer_args('python3 -c ' + shlex.quote(code)),
                          data=source.read_bytes())

    async def upload_dir(self, source_dir, target_dir):
        target = self.upload_target(target_dir)
        source_dir = self.upload_source(source_dir)
        bundle = io.BytesIO()
        with tarfile.open(fileobj=bundle, mode='w') as archive:
            for path in sorted(Path(source_dir).rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlink upload is unsupported')
                archive.add(path, arcname=path.relative_to(source_dir), recursive=False)
        if bundle.tell() > 4 * 1024**2:
            raise ValueError('Native directory upload exceeds its size bound')
        code = ('import pathlib,sys,tarfile;p=pathlib.Path(' + repr(target) +
                ');p.mkdir(parents=True,exist_ok=True);'
                'tarfile.open(fileobj=sys.stdin.buffer,mode="r|").extractall(p,filter="data")')
        await self.native(self.transfer_args('python3 -c ' + shlex.quote(code)),
                          data=bundle.getvalue())

    def upload_source(self, source):
        source = Path(source)
        if not any(source.resolve().is_relative_to(p.resolve())
                   for p in (self.environment_dir.parent, self.trial_paths.trial_dir)):
            raise ValueError('Native upload source is outside the reviewed task/trial')
        return source

    async def download_file(self, source_path, target_path):
        source = self.checked_path(source_path)
        code = ('import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(' +
                repr(source) + ').read_bytes())')
        _, raw, _ = await self.native(self.transfer_args('python3 -c ' + shlex.quote(code)))
        if len(raw) > 8 * 1024**2:
            raise ValueError('Native file download exceeds its size bound')
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        Path(target_path).write_bytes(raw)

    async def download_dir(self, source_dir, target_dir):
        source = self.checked_path(source_dir)
        code = ('import pathlib,sys,tarfile;p=pathlib.Path(' + repr(source) +
                ');a=tarfile.open(fileobj=sys.stdout.buffer,mode="w|");'
                '[a.add(f,arcname=f.relative_to(p),recursive=False) '
                'for f in sorted(p.rglob("*"))];a.close()')
        _, raw, _ = await self.native(self.transfer_args('python3 -c ' + shlex.quote(code)))
        if len(raw) > 16 * 1024**2:
            raise ValueError('Native directory download exceeds its size bound')
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            if any(not (m.isfile() or m.isdir()) for m in archive.getmembers()):
                raise ValueError('Native download contains unsupported links')
            archive.extractall(target, filter='data')
