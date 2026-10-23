"""Run the real authenticated backend through a free temporary HTTPS tunnel."""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def private_file(path: Path):
    if path.is_symlink():
        raise ValueError('Regular private hosting file required')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.chmod(path, 0o600)
    return os.fdopen(fd, 'a')


def serve(root: Path):
    folder = root / 'results/public-hosting'
    folder.mkdir(mode=0o700, exist_ok=True)
    with private_file(folder / 'launcher.lock') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 8770)) == 0:
                raise ValueError('The public backend is already running; leave it intact')
        binary = root.parent / 'work/cloudflared-2026.10.3/cloudflared'
        if not binary.is_file() or binary.is_symlink():
            raise ValueError('Install pinned cloudflared; see docs/public-backend.md')
        access = folder / 'access-code.txt'
        if not access.exists():
            with private_file(access) as output:
                output.write(secrets.token_urlsafe(36) + '\n')
        origin_file = folder / 'origin.txt'
        with private_file(origin_file):
            origin_file.write_text('')
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL',
            'SSL_CERT_FILE', 'SSL_CERT_DIR') if k in os.environ}
        tunnel_log = folder / 'tunnel.log'
        offset = tunnel_log.stat().st_size if tunnel_log.exists() else 0
        with private_file(folder / 'server.log') as server_log, private_file(tunnel_log):
            server = subprocess.Popen([sys.executable, '-m', 'skillguard.ui.public_server',
                '--origin-file', str(origin_file), '--access-file', str(access)],
                cwd=root, env=env, stdout=server_log, stderr=subprocess.STDOUT)
            tunnel = None
            try:
                tunnel = subprocess.Popen([str(binary), 'tunnel', '--no-autoupdate',
                    '--url', 'http://127.0.0.1:8770', '--metrics', '127.0.0.1:0',
                    '--logfile', str(tunnel_log)], cwd=root, env=env,
                    stdout=server_log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if server.poll() is not None or tunnel.poll() is not None:
                        raise RuntimeError('Public service failed; inspect private hosting logs')
                    content = tunnel_log.read_text()[offset:]
                    urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', content)
                    if urls:
                        origin_file.write_text(urls[-1] + '\n')
                        print('Real backend:', urls[-1], flush=True)
                        print('Private access code:', access, flush=True)
                        print('Temporary endpoint; this Mac must remain running.', flush=True)
                        break
                    time.sleep(1)
                else:
                    raise TimeoutError('No public endpoint received; no model calls attempted')
                if sys.platform == 'darwin':
                    subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(server.pid)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                server.wait()
            finally:
                if tunnel and tunnel.poll() is None:
                    tunnel.terminate()
                    tunnel.wait(timeout=30)
                if server.poll() is None:
                    server.terminate()
                server.wait()


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with contextlib.suppress(KeyboardInterrupt):
        serve(Path(__file__).resolve().parents[1])
