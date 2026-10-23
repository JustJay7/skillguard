#!/bin/sh
# Fixed test infrastructure only. Run as root in the dedicated Linux VM.
set -eu
test "$(id -u)" = 0
probe_name=${1:?existing test name required}
python3 - "$probe_name" <<'PY'
import re, sys
if not re.fullmatch(r'sg-linux-trace-[a-z0-9-]+', sys.argv[1]) or len(sys.argv[1]) > 19:
    raise SystemExit('Dedicated test name must meet native OpenShell constraints')
PY
install -m 700 -d /root/.config/openshell /root/.local/state/openshell/tls /root/sg-image
cat > /root/.config/openshell/gateway.toml <<'CONFIG'
[openshell]
version = 2
[openshell.gateway]
compute_driver = "docker"
CONFIG
if [ -z "$(ls -A /root/.local/state/openshell/tls)" ]; then
    openshell-gateway generate-certs --output-dir /root/.local/state/openshell/tls \
        --server-san localhost --server-san 127.0.0.1 \
        --server-san host.openshell.internal > /root/generate-certs.txt 2>&1
fi
if ! systemctl is-active --quiet skillguard-openshell; then
    systemd-run --unit=skillguard-openshell --uid=root \
        --property=SetLoginEnvironment=yes --property=UMask=0077 \
        --setenv=OPENSHELL_LOCAL_TLS_DIR=/root/.local/state/openshell/tls /usr/bin/openshell-gateway
fi
if ! openshell gateway add https://127.0.0.1:17670 --local --name openshell \
    > /root/gateway-registration.txt 2>&1; then
    if ! grep -F "Gateway 'openshell' already exists." /root/gateway-registration.txt >/dev/null; then
        cat /root/gateway-registration.txt
        exit 1
    fi
fi
python3 - <<'PY'
import subprocess, time
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    result = subprocess.run(['openshell','status'], capture_output=True, text=True, timeout=5)
    if (result.returncode == 0 and 'Status: Connected' in result.stdout
        and 'Gateway: openshell' in result.stdout
        and 'Server: https://127.0.0.1:17670' in result.stdout):
        print('Native gateway connected')
        break
    time.sleep(.1)
else:
    raise SystemExit('Native gateway readiness not established')
PY
cat > /root/sg-image/Dockerfile <<'IMAGE'
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
RUN groupadd -g 1000 sandbox && useradd -u 1000 -g 1000 -M -d /sandbox sandbox && mkdir -p /sandbox && chown 1000:1000 /sandbox
USER sandbox:sandbox
WORKDIR /sandbox
IMAGE
env DOCKER_BUILDKIT=0 docker build -t skillguard-trace:fixed /root/sg-image > /root/image-build.txt 2>&1
cat > /root/trace-policy.yaml <<'POLICY'
version: 1
filesystem_policy:
  include_workdir: true
  read_only: [/bin, /usr, /lib, /proc, /dev/urandom, /etc, /var/log]
  read_write: [/tmp, /dev/null]
landlock:
  compatibility: hard_requirement
process:
  run_as_user: "1000"
  run_as_group: "1000"
POLICY
if [ "${2:-}" != "prepare-only" ]; then
    openshell sandbox create --name "$probe_name" --from skillguard-trace:fixed \
        --policy /root/trace-policy.yaml --detach --no-auto-providers -- sleep 3600
fi
