"""Fixed fake-data OpenShell/strace integration experiment, run as guest root.

This is not a collector service, evaluator harness, or arbitrary skill runner.
An existing workload must be Ready. All artifacts stay outside its filesystem.
Neither successful markers nor this probe establish complete hostile-code coverage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"native command failed: {args[:3]}: {result.stderr[:500]}")
    return result.stdout


def main() -> None:
    if os.getuid() != 0 or len(sys.argv) != 2:
        raise SystemExit("Run in the dedicated Linux guest as root with existing sandbox name")
    name = sys.argv[1]
    if not re.fullmatch(r"sg-linux-trace-[a-z0-9-]+", name):
        raise SystemExit("Only dedicated fixed-probe workloads are accepted")
    os.umask(0o077)
    run = Path("/root") / ("trace-evidence-" + uuid.uuid4().hex[:8])
    run.mkdir(mode=0o700)
    report = {"run": str(run), "sandbox": name, "model_calls": 0,
              "complete": False, "activation_eligible": False}
    tracer = None
    listener = socket.socket()
    try:
        native = json.loads(command(["openshell", "sandbox", "get", name, "-o", "json"]))
        (run / "native-sandbox.json").write_text(json.dumps(native, indent=2))
        if native["phase"] != "Ready":
            raise RuntimeError("Workload is not Ready")
        ids = command(["docker", "ps", "-q", "--filter",
                       "label=openshell.ai/isolation-role=sandbox"]).split()
        containers = [json.loads(command(["docker", "inspect", value]))[0] for value in ids]
        matching = [value for value in containers if value["Name"].startswith(
            f"/openshell-default--{name}-")]
        if len(matching) != 1:
            raise RuntimeError("Ambiguous native workload identity")
        container = matching[0]
        pid = container["State"]["Pid"]
        selected = {"id": container["Id"], "pid": pid, "image": container["Image"],
                    "user": container["Config"]["User"], "mounts": container["Mounts"],
                    "cap_drop": container["HostConfig"]["CapDrop"],
                    "cap_add": container["HostConfig"]["CapAdd"],
                    "security_opt": container["HostConfig"]["SecurityOpt"],
                    "network_mode": container["HostConfig"]["NetworkMode"]}
        (run / "container.json").write_text(json.dumps(selected, indent=2))
        if selected["user"] != "1000:1000" or selected["network_mode"] != "none":
            raise RuntimeError("Unexpected workload privilege/network boundary")
        ssh_config = run / "ssh_config"
        ssh_config.write_text(command(["openshell", "sandbox", "ssh-config", name]))
        hosts = re.findall(r"^Host (\S+)$", ssh_config.read_text(), re.M)
        if len(hosts) != 1 or not hosts[0].startswith(f"openshell-{name}."):
            raise RuntimeError("Unexpected native SSH target")
        canary = run / "host-only-fake-canary.txt"
        canary.write_text("FAKE_OPERATOR_ONLY_CANARY")
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(0.2)
        port = listener.getsockname()[1]
        report["operator_listener_port"] = port
        # Attach to all current workload processes; -f follows ordinary future forks.
        pids = command(["docker", "top", container["Id"], "-eo", "pid"]).split()[1:]
        if str(pid) not in pids or not all(value.isdigit() for value in pids):
            raise RuntimeError("Unexpected native process listing")
        args = ["strace", "-f", "-ttt", "-yy", "-s", "128", "-e",
                "trace=%file,%process,%network,read,write,mmap,mprotect,munmap,ptrace", "-e",
                "raw=read,write,recvfrom,sendto,recvmsg,sendmsg", "-o", str(run / "trace.txt")]
        for value in pids:
            args.extend(["-p", value])
        with (run / "tracer.stderr").open("w") as stderr:
            tracer = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=stderr)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                status = Path(f"/proc/{pid}/status").read_text()
                if f"TracerPid:\t{tracer.pid}\n" in status:
                    break
                if tracer.poll() is not None:
                    raise RuntimeError("External tracer exited before attachment")
                time.sleep(0.1)
            else:
                raise RuntimeError("External attachment was not confirmed")
            report.update({"tracer_pid": tracer.pid, "attached_pids": pids,
                           "attachment_confirmed": True,
                           "observer_pid_namespace": os.readlink("/proc/self/ns/pid"),
                           "workload_pid_namespace": os.readlink(f"/proc/{pid}/ns/pid")})
            probe = '''
import ctypes, errno, json, mmap, os, platform, signal, socket, stat, subprocess
from pathlib import Path
root = Path('/sandbox/fixed-trace-probe')
root.mkdir(exist_ok=True)
receipt = root / 'receipt.txt'
receipt.write_text('Maple Corner Cafe: CAD 13.80')
output = root / 'output.txt'
output.write_text('processed:' + receipt.read_text())
# Same directory, independent positive controls for the native TMPFILE flag bug.
directory_probe = root / 'directory-open-control'
directory_probe.mkdir()
fd = os.open(directory_probe, os.O_RDONLY | os.O_DIRECTORY)
directory_open_checks = {'directory_path': str(directory_probe),
    'directory_fd': fd, 'directory_is_directory': stat.S_ISDIR(os.fstat(fd).st_mode),
    'directory_access_mode': os.O_RDONLY, 'tmpfile_supported': False}
os.close(fd)
try:
    fd = os.open(directory_probe, os.O_RDWR | os.O_TMPFILE, 0o600)
    directory_open_checks.update(tmpfile_supported=True, tmpfile_fd=fd,
        tmpfile_is_regular=stat.S_ISREG(os.fstat(fd).st_mode),
        tmpfile_link_count=os.fstat(fd).st_nlink)
    os.write(fd, b'FAKE_UNNAMED_FILE')
    os.close(fd)
except OSError as error:
    directory_open_checks['tmpfile_errno'] = error.errno
# Namespace and zero-byte content changes require no write syscall.
mutation_checks = {}
new = root / 'exclusive-empty.txt'
fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.close(fd)
mutation_checks['exclusive_create'] = new.is_file() and new.stat().st_size == 0
existing = root / 'existing-create.txt'
existing.write_text('FAKE_EXISTING_FILE')
fd = os.open(existing, os.O_RDWR | os.O_CREAT, 0o600)
os.close(fd)
mutation_checks['existing_create'] = existing.read_text() == 'FAKE_EXISTING_FILE'
truncated = root / 'truncated.txt'
truncated.write_text('FAKE_CONTENT_TO_TRUNCATE')
fd = os.open(truncated, os.O_WRONLY | os.O_TRUNC)
os.close(fd)
mutation_checks['open_truncate'] = truncated.stat().st_size == 0
rename_source = root / 'rename-source.txt'
rename_target = root / 'rename-target.txt'
rename_source.write_text('FAKE_RENAME_SOURCE')
os.rename(rename_source, rename_target)
mutation_checks['rename'] = not rename_source.exists() and rename_target.is_file()
link = root / 'hardlink.txt'
os.link(rename_target, link)
mutation_checks['hardlink'] = link.stat().st_ino == rename_target.stat().st_ino
symlink = root / 'symlink.txt'
os.symlink('rename-target.txt', symlink)
mutation_checks['symlink'] = os.readlink(symlink) == 'rename-target.txt'
removed = root / 'removed.txt'
removed.write_text('FAKE_DELETE_SOURCE')
removed.unlink()
mutation_checks['unlink'] = not removed.exists()
directory = root / 'removed-directory'
directory.mkdir()
directory.rmdir()
mutation_checks['directory_changes'] = not directory.exists()
# Compare live handles with hardlinks, renamed/replaced entries and FD reuse.
identity_source = root / 'identity-source.txt'
identity_alias = root / 'identity-hardlink.txt'
identity_renamed = root / 'identity-renamed.txt'
identity_reused = root / 'identity-reused.txt'
original_bytes = b'FAKE_IDENTITY_ORIGINAL'
replacement_bytes = b'FAKE_IDENTITY_REPLACEMENT'
identity_source.write_bytes(original_bytes)
def identity_snapshot(fd):
    current = os.fstat(fd)
    return {'fd': fd, 'device_major': os.major(current.st_dev),
        'device_minor': os.minor(current.st_dev), 'inode': current.st_ino}
identity_checks = {'paths': {'source': str(identity_source), 'alias': str(identity_alias),
    'renamed': str(identity_renamed), 'reused': str(identity_reused)}, 'observations': {}}
identity_fd = os.open(identity_source, os.O_RDONLY)
try:
    identity_checks['observations']['original_open'] = identity_snapshot(identity_fd)
    os.link(identity_source, identity_alias)
    os.rename(identity_source, identity_renamed)
    read = os.read(identity_fd, 128)
    identity_checks['observations']['original_after_rename'] = (
        identity_snapshot(identity_fd) | {'bytes_read': len(read),
            'content_correct': read == original_bytes})
    alias_fd = os.open(identity_alias, os.O_RDONLY)
    try:
        read = os.read(alias_fd, 128)
        identity_checks['observations']['hardlink_read'] = (
            identity_snapshot(alias_fd) | {'bytes_read': len(read),
                'content_correct': read == original_bytes})
    finally:
        os.close(alias_fd)
    identity_renamed.unlink()
    identity_renamed.write_bytes(replacement_bytes)
    replacement_fd = os.open(identity_renamed, os.O_RDONLY)
    try:
        read = os.read(replacement_fd, 128)
        identity_checks['observations']['replacement_read'] = (
            identity_snapshot(replacement_fd) | {'bytes_read': len(read),
                'content_correct': read == replacement_bytes})
        os.lseek(identity_fd, 0, os.SEEK_SET)
        read = os.read(identity_fd, 128)
        identity_checks['observations']['original_after_replacement'] = (
            identity_snapshot(identity_fd) | {'bytes_read': len(read),
                'content_correct': read == original_bytes})
    finally:
        os.close(replacement_fd)
finally:
    os.close(identity_fd)
identity_reused.write_bytes(b'FAKE_REUSED_DESCRIPTOR')
reused_fd = os.open(identity_reused, os.O_RDONLY)
try:
    read = os.read(reused_fd, 128)
    identity_checks['observations']['reused_descriptor_read'] = (
        identity_snapshot(reused_fd) | {'bytes_read': len(read),
            'content_correct': read == b'FAKE_REUSED_DESCRIPTOR'})
finally:
    os.close(reused_fd)
# Metadata can change access without a completed content-write syscall.
metadata_file = root / 'metadata-file.txt'
metadata_file.write_text('FAKE_METADATA_CONTENT')
metadata_checks = {}
os.chmod(metadata_file, 0o640)
metadata_checks['path_permissions'] = metadata_file.stat().st_mode & 0o777 == 0o640
with metadata_file.open('rb') as source:
    os.fchmod(source.fileno(), 0o600)
    metadata_checks['descriptor_permissions'] = metadata_file.stat().st_mode & 0o777 == 0o600
    os.fchown(source.fileno(), os.getuid(), os.getgid())
    metadata_checks['descriptor_ownership'] = os.fstat(source.fileno()).st_uid == os.getuid()
os.chown(metadata_file, os.getuid(), os.getgid())
metadata_checks['path_ownership'] = metadata_file.stat().st_uid == os.getuid()
os.chown(symlink, os.getuid(), os.getgid(), follow_symlinks=False)
metadata_checks['symlink_ownership'] = symlink.lstat().st_uid == os.getuid()
metadata_checks['content_unchanged'] = metadata_file.read_text() == 'FAKE_METADATA_CONTENT'
# Known fake-data API probes, not attacks or evaluation dataset generation.
initial = b'FAKE_MMAP_SOURCE'
mapped_read = root / 'mapped-read.txt'
mapped_private = root / 'mapped-private.txt'
mapped_shared = root / 'mapped-shared.txt'
for path in (mapped_read, mapped_private, mapped_shared):
    path.write_bytes(initial)
with mapped_read.open('rb') as source:
    with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as region:
        mmap_read_correct = region[:] == initial
with mapped_private.open('rb') as source:
    with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_COPY) as region:
        region[0:1] = b'X'
        mmap_private_changed = region[0:1] == b'X'
mmap_private_source_unchanged = mapped_private.read_bytes() == initial
with mapped_shared.open('r+b') as source:
    with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_WRITE) as region:
        region[0:1] = b'Y'
        region.flush()
mmap_shared_source_changed = mapped_shared.read_bytes() == b'Y' + initial[1:]
# A shared map starts read-only, then gains write permission. The content change
# uses memory, so ordinary completed file writes cannot represent this operation.
libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int,
                     ctypes.c_int, ctypes.c_long]
libc.mmap.restype = ctypes.c_void_p
libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
libc.mprotect.restype = ctypes.c_int
libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
libc.munmap.restype = ctypes.c_int
page_size = os.sysconf('SC_PAGE_SIZE')
mapped_upgrade = root / 'mapped-upgrade.txt'
mapped_upgrade.write_bytes(b'A' * page_size)
lifecycle_checks = {'page_size': page_size, 'thread_vtid': os.getpid()}
with mapped_upgrade.open('r+b') as source:
    address = libc.mmap(None, page_size, mmap.PROT_READ, mmap.MAP_SHARED, source.fileno(), 0)
    if address == ctypes.c_void_p(-1).value or address is None:
        raise RuntimeError('Fixed shared mapping failed')
    lifecycle_checks['address'] = format(address, 'X')
    try:
        changed = libc.mprotect(address, page_size, mmap.PROT_READ | mmap.PROT_WRITE)
        lifecycle_checks['mprotect_returncode'] = changed
        if changed == 0:
            ctypes.c_char.from_address(address).value = b'Z'
            lifecycle_checks['shared_source_changed'] = mapped_upgrade.read_bytes() == (
                b'Z' + b'A' * (page_size - 1))
    finally:
        lifecycle_checks['munmap_returncode'] = libc.munmap(address, page_size)
    ctypes.set_errno(0)
    lifecycle_checks['failed_mprotect_returncode'] = libc.mprotect(
        address, page_size, mmap.PROT_READ)
    lifecycle_checks['failed_mprotect_errno'] = ctypes.get_errno()
transfer_source = root / 'transfer-source.txt'
transfer_source.write_bytes(initial)
transfer_checks = {}
for kind in ('sendfile', 'copy_file_range', 'splice'):
    target = root / (kind + '-output.txt')
    with transfer_source.open('rb') as source, target.open('wb') as sink:
        if kind == 'sendfile':
            count = os.sendfile(sink.fileno(), source.fileno(), 0, len(initial))
        elif kind == 'copy_file_range':
            count = os.copy_file_range(source.fileno(), sink.fileno(), len(initial))
        else:
            reader, writer = os.pipe()
            try:
                to_pipe = os.splice(source.fileno(), writer, len(initial))
                count = os.splice(reader, sink.fileno(), to_pipe)
            finally:
                os.close(reader)
                os.close(writer)
    transfer_checks[kind] = count == len(initial) and target.read_bytes() == initial
child = subprocess.check_output(['/bin/echo', 'CHILD_OK'], text=True).strip()
libc = ctypes.CDLL(None, use_errno=True)
# Linux aarch64 numbers read from installed libc's gnu/b64/aarch64 source.
# Setup submits no I/O; enter/register use an invalid FD. Never submit a request.
if platform.machine() != 'aarch64':
    raise RuntimeError('Fixed native async check requires verified Linux aarch64 numbers')
libc.syscall.restype = ctypes.c_long
async_checks = {}
params = ctypes.create_string_buffer(4096)
async_args = {
 'io_uring_setup': (425, (ctypes.c_uint(1), ctypes.byref(params))),
 'io_uring_enter': (426, (ctypes.c_long(-1), ctypes.c_uint(0), ctypes.c_uint(0),
                         ctypes.c_uint(0), ctypes.c_void_p(), ctypes.c_size_t(0))),
 'io_uring_register': (427, (ctypes.c_long(-1), ctypes.c_uint(0), ctypes.c_void_p(),
                            ctypes.c_uint(0))),
}
for kind, (number, values) in async_args.items():
    ctypes.set_errno(0)
    result = libc.syscall(ctypes.c_long(number), *values)
    async_checks[kind] = {'result': result, 'errno': ctypes.get_errno()}
    if kind == 'io_uring_setup' and result >= 0:
        os.close(result)
ctypes.set_errno(0)
ptrace_result = libc.ptrace(0, 0, None, None)
ptrace_errno = ctypes.get_errno()
# Fake IPC and loopback controls; use the existing native network mediation.
ipc_checks = {}
left, right = socket.socketpair()
try:
    ipc_checks['unix_fds'] = [left.fileno(), right.fileno()]
    ipc_checks['unix_sent'] = left.sendmsg([b'FAKE_UNIX_MESSAGE'])
    ipc_checks['unix_received'] = len(right.recvmsg(64)[0])
    ipc_checks['unix_written'] = os.write(left.fileno(), b'FAKE_UNIX_WRITE')
    ipc_checks['unix_read'] = len(os.read(right.fileno(), 64))
finally:
    left.close(); right.close()
reader, writer = os.pipe()
try:
    ipc_checks['pipe_fds'] = [reader, writer]
    ipc_checks['pipe_written'] = os.writev(writer, [b'FAKE_PIPE_WRITE'])
    ipc_checks['pipe_read'] = os.readv(reader, [bytearray(64)])
finally:
    os.close(reader); os.close(writer)
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.settimeout(1)
try:
    udp.bind(('127.0.0.1', 0))
    ipc_checks['udp_fd'] = udp.fileno()
    ipc_checks['udp_target'] = list(udp.getsockname())
    ipc_checks['udp_sent'] = udp.sendto(b'FAKE_UDP_MESSAGE', udp.getsockname())
    ipc_checks['udp_received'] = len(udp.recvfrom(64)[0])
except OSError as error:
    ipc_checks['udp_errno'] = error.errno
finally:
    udp.close()
s = socket.socket()
s.settimeout(2)
network_errno = s.connect_ex(('127.0.0.1', PORT))
s.close()
# Harmless escape check documented by upstream strace: no network or secrets.
callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
@callback_type
def untraced_child(_):
    fd = os.open('/sandbox/fixed-trace-probe/untraced-marker.txt',
                 os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, b'FAKE_UNTRACED_CHILD_MARKER')
    os.close(fd)
    return 0
stack = ctypes.create_string_buffer(131072)
libc.clone.argtypes = [callback_type, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
libc.clone.restype = ctypes.c_int
ctypes.set_errno(0)
escape_pid = libc.clone(untraced_child, ctypes.addressof(stack) + len(stack),
                        0x00800000 | signal.SIGCHLD, None)
escape_errno = ctypes.get_errno()
escape_status = os.waitpid(escape_pid, 0)[1] if escape_pid > 0 else None
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
def visibility(path):
    try:
        return {'visible': Path(path).exists(), 'errno': 0}
    except OSError as error:
        return {'visible': False, 'errno': error.errno}
print(json.dumps({
 'uid': os.getuid(), 'cap_eff': status['CapEff'].strip(),
 'no_new_privs': status['NoNewPrivs'].strip(), 'seccomp': status['Seccomp'].strip(),
 'functional_passed': output.read_text() == 'processed:Maple Corner Cafe: CAD 13.80',
 'mmap_read_correct': mmap_read_correct,
 'mmap_private_changed': mmap_private_changed,
 'mmap_private_source_unchanged': mmap_private_source_unchanged,
 'mmap_shared_source_changed': mmap_shared_source_changed,
 'mapping_lifecycle_checks': lifecycle_checks,
 'directory_open_checks': directory_open_checks,
 'file_transfer_checks': transfer_checks,
 'file_mutation_checks': mutation_checks,
 'file_identity_checks': identity_checks,
 'file_metadata_checks': metadata_checks,
 'socket_ipc_checks': ipc_checks,
 'io_uring_checks': async_checks,
 'child_output': child, 'ptrace_result': ptrace_result, 'ptrace_errno': ptrace_errno,
 'network_errno': network_errno, 'host_canary_visibility': visibility(HOST_CANARY),
 'observer_log_visibility': visibility(TRACE_PATH),
 'provider_credentials_present': any(os.environ.get(k) for k in
   ['NEBIUS_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'NVIDIA_API_KEY']),
 'clone_untraced_pid': escape_pid, 'clone_untraced_errno': escape_errno,
 'clone_untraced_status': escape_status,
 'clone_untraced_marker_correct': (Path('/sandbox/fixed-trace-probe/untraced-marker.txt')
   .read_bytes() == b'FAKE_UNTRACED_CHILD_MARKER') if escape_pid > 0 else False,
}))
'''.replace("PORT", str(port)).replace("HOST_CANARY", repr(str(canary))).replace(
                "TRACE_PATH", repr(str(run / "trace.txt")))
            (run / "fixed-probe.py").write_text(probe)
            report["probe_sha256"] = hashlib.sha256(probe.encode()).hexdigest()
            result = subprocess.run(["ssh", "-F", str(ssh_config), hosts[0],
                                     "python -c " + shlex.quote(probe)],
                                    capture_output=True, text=True, timeout=45)
            (run / "workload.stdout").write_text(result.stdout)
            (run / "workload.stderr").write_text(result.stderr)
            report["workload_returncode"] = result.returncode
            if result.returncode:
                raise RuntimeError("Fixed workload probe failed; inspect saved native output")
            report["workload_checks"] = json.loads(result.stdout)
            try:
                connection, _ = listener.accept()
                connection.close()
                report["operator_listener_received_connection"] = True
            except TimeoutError:
                report["operator_listener_received_connection"] = False
            report["operator_canary_unchanged"] = canary.read_text() == "FAKE_OPERATOR_ONLY_CANARY"
            report["observer_alive_after_probe"] = tracer.poll() is None
    except Exception as error:
        report["error"] = str(error)
    finally:
        listener.close()
        stopped = subprocess.run(["openshell", "sandbox", "stop", name],
                                 capture_output=True, text=True, timeout=60)
        (run / "stop.txt").write_text(stopped.stdout + stopped.stderr)
        report["stop_returncode"] = stopped.returncode
        try:
            report["stopped_phase"] = json.loads(command(
                ["openshell", "sandbox", "get", name, "-o", "json"]))["phase"]
        except Exception as error:
            report["stop_readback_error"] = str(error)
        if tracer:
            try:
                report["tracer_returncode"] = tracer.wait(timeout=10)
            except subprocess.TimeoutExpired:
                tracer.terminate()
                report["tracer_returncode"] = tracer.wait(timeout=10)
                report["tracer_required_termination"] = True
        if (run / "trace.txt").is_file():
            raw = (run / "trace.txt").read_bytes()
            report["trace_sha256"] = hashlib.sha256(raw).hexdigest()
            report["trace_bytes"] = len(raw)
        report["limitations"] = [
            "Fixed fake-data probe only, no candidate or generated code evaluated",
            "Attachment occurs after startup; earlier behavior is not captured",
            "strace -p cannot use --kill-on-exit; no fail-closed observer guarantee",
            "CLONE_UNTRACED may escape -f; verify the explicit child marker separately",
            "No complete envelope, event-loss proof, Skill Lift, or activation claim",
        ]
        (run / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    if report.get("error") or report.get("stopped_phase") != "Stopped":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
