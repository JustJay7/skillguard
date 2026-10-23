"""Immutable-image adapter for one known native Hermes pending derivative.

No generic skill runner, evaluation harness, model call or enforcement layer.
Use existing OpenShell policy/Docker and operator-owned native capture only.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from scripts.hermes_procedure_use_probe import LEARNED_SHA
from skillguard.review.snapshot import digest, snapshot_digest
from skillguard.review.store import ReviewStore

EXPECTED = {
    "date": "2026-10-02",
    "vendor": "Harbor Mock Grocery",
    "subtotal": 21.50,
    "tax": 3.23,
    "total": 24.73,
    "needs_clarification": False,
}
RECEIPT = (
    "Harbor Mock Grocery\n2026-10-02\nSubtotal: CAD 21.50\nTax: CAD 3.23\nTotal paid: CAD 24.73\n"
)

LAUNCHER = """import hashlib, json, os, subprocess
from pathlib import Path
root = Path('/opt/skillguard-candidate')
def sha():
    files = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
report = {'candidate_sha256_before':sha(), 'launcher_pid':os.getpid()}
try:
    process = subprocess.Popen(['python', str(root/'scripts/parse_receipt.py'),
                                '/opt/skillguard-fixtures/input.txt',
                                '/sandbox/receipt-output.json'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    report['parser_pid'] = process.pid
    stdout, stderr = process.communicate(timeout=30)
    report.update({'returncode':process.returncode,'stdout':stdout,'stderr':stderr})
    output = Path('/sandbox/receipt-output.json')
    report['record'] = json.loads(output.read_text()) if output.exists() else None
except Exception as error:
    report['error'] = str(error)
    if 'process' in globals() and process.poll() is None:
        process.kill()
        process.communicate()
report['candidate_sha256_after'] = sha()
Path('/sandbox/candidate-execution.json').write_text(json.dumps(report))
Path('/sandbox/startup-marker.txt').write_text('FAKE_STARTUP_MARKER')
os.execv('/usr/bin/sleep', ['sleep', '3600'])
"""


def candidate_payload(root: Path, preparation: Path) -> dict:
    root, preparation = root.resolve(), preparation.resolve()
    if not preparation.resolve().is_relative_to(root / "results/integration"):
        raise ValueError("preparation must be an archived local integration result")
    data = json.loads(preparation.read_text())
    if data.get("parent_candidate_sha256") != LEARNED_SHA or not data.get("preparation_passed"):
        raise ValueError("only the known learned-guide derivative is accepted")
    store_path = Path(data["store"])
    if not store_path.resolve().is_relative_to(preparation.parent):
        raise ValueError("preparation review store escaped its archived run")
    review = ReviewStore(store_path).get(data["review_id"])
    static = review["latest"].get("static", {})
    if static.get("overall_status") != "passed" or static.get("incomplete_scans") != []:
        raise ValueError("candidate requires complete native Tier 1 checks")
    candidate = Path(review["snapshot"])
    parent = digest(json.dumps({"SKILL.md": digest((candidate / "SKILL.md").read_bytes())},
                               sort_keys=True).encode())
    if parent != LEARNED_SHA:
        raise ValueError("prepared candidate changed its exact parent guide")
    if snapshot_digest(candidate) != data.get("candidate_sha256"):
        raise ValueError("prepared candidate changed")
    paths = {p.relative_to(candidate).as_posix() for p in candidate.rglob("*") if p.is_file()}
    if paths != {"SKILL.md", "scripts/parse_receipt.py"}:
        raise ValueError("fixed candidate accepts only its guide and parser")
    if digest((candidate / "scripts/parse_receipt.py").read_bytes()) != data["parser_sha256"]:
        raise ValueError("prepared parser changed")
    return {
        "candidate_sha256": review["candidate_sha256"],
        "review_id": data["review_id"],
        "store": str(store_path),
        "preparation": str(preparation),
        "parser_sha256": data["parser_sha256"],
        "files": {
            name: base64.b64encode((candidate / name).read_bytes()).decode() for name in paths
        },
    }


def execution_launcher(*, compare_control: bool = False) -> str:
    launcher = LAUNCHER
    if compare_control:
        launcher = launcher.replace("try:\n    process =", """control = subprocess.run(
                         ['python', '/opt/skillguard-baseline.py'],
                         capture_output=True, text=True, timeout=30)
report['control_returncode'] = control.returncode
try:
    process =""")
    return launcher


def guest_image_source(payload: dict, *, compare_control: bool = False) -> str:
    return (
        '''import base64, hashlib, json, os, subprocess
from pathlib import Path
os.umask(0o077)
data = PAYLOAD
root = Path('/root') / ('candidate-image-' + data['candidate_sha256'][:12])
root.mkdir(exist_ok=True)
files = {name:base64.b64decode(value, validate=True) for name,value in data['files'].items()}
if set(files) != {'SKILL.md','scripts/parse_receipt.py'}:
    raise SystemExit('Unexpected image sources')
actual = hashlib.sha256(json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in files.items()},
                                 sort_keys=True).encode()).hexdigest()
if actual != data['candidate_sha256']:
    raise SystemExit('Transferred source identity changed')
for name, raw in files.items():
    path = root/'candidate'/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o444)
(root/'candidate').chmod(0o755)
(root/'candidate/scripts').chmod(0o755)
(root/'input.txt').write_text(RECEIPT)
(root/'launch.py').write_text(LAUNCHER)
(root/'baseline.py').write_text('pass\\n')
(root/'input.txt').chmod(0o444)
(root/'launch.py').chmod(0o444)
(root/'baseline.py').chmod(0o444)
(root/'Dockerfile').write_text("""FROM skillguard-trace:fixed
USER root
COPY candidate /opt/skillguard-candidate
COPY input.txt /opt/skillguard-fixtures/input.txt
COPY launch.py /opt/skillguard-launch.py
COPY baseline.py /opt/skillguard-baseline.py
RUN chmod -R a-w /opt/skillguard-candidate /opt/skillguard-fixtures /opt/skillguard-launch.py
RUN chmod a-w /opt/skillguard-baseline.py
USER sandbox:sandbox
WORKDIR /sandbox
""")
image = 'skillguard-candidate:' + data['candidate_sha256'][:12]
with (root/'build.txt').open('w') as log:
    subprocess.run(['env','DOCKER_BUILDKIT=0','docker','build','-t',image,str(root)],
                   stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
inspect = json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
policy = Path('/root/candidate-policy.yaml')
policy.write_text("""version: 1
filesystem_policy:
  include_workdir: true
  read_only: [/bin, /usr, /lib, /proc, /dev/urandom, /etc, /var/log, /opt]
  read_write: [/tmp, /dev/null]
landlock:
  compatibility: hard_requirement
process:
  run_as_user: "1000"
  run_as_group: "1000"
""")
print(json.dumps({'image':image,'image_id':inspect['Id'],'source_sha256':actual,
                  'launcher_sha256':hashlib.sha256((root/'launch.py').read_bytes()).hexdigest(),
                  'control_sha256':hashlib.sha256((root/'baseline.py').read_bytes()).hexdigest(),
                  'control_kind':CONTROL_KIND,
                  'policy':str(policy),'source_directory':str(root)}))
'''.replace("PAYLOAD", repr(payload))
        .replace("RECEIPT", repr(RECEIPT))
        .replace("LAUNCHER", repr(execution_launcher(compare_control=compare_control)))
        .replace("CONTROL_KIND", repr(
            "empty_python_control" if compare_control else "not_executed"))
    )
