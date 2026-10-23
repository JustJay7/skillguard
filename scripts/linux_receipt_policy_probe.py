"""Same-image native file-policy canary for the known repaired receipt resource.

Native OpenShell owns enforcement/execution. This is an operator-controlled
fake-file trial, not a generic agent harness, collector or approval path.
"""
from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path

from scripts.learned_candidate_image import EXPECTED, RECEIPT, candidate_payload
from scripts.linux_runner import prepare_environment
from scripts.receipt_workflow import recorded_command
from scripts.run_native_evaluation import PREFIX
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def validate_trial(review: dict) -> dict:
    latest = review["latest"]
    native = latest.get("candidate_execution", {})
    draft = latest.get("policy_draft", {})
    contract = latest.get("contract")
    if (not contract or native.get("functional_passed") is not True
            or native.get("candidate_sha256") != review["candidate_sha256"]
            or native.get("failure_reasons") != []
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", native.get("image_id", ""))
            or latest.get("frozen_resource_evaluation", {}).get("functional_passed") is not True
            or draft.get("candidate_sha256") != review["candidate_sha256"]
            or draft.get("contract_sha256") != digest(
                json.dumps(contract, sort_keys=True).encode())):
        raise ValueError("File trial requires current passing native execution, checks and policy")
    return {"image_id": native["image_id"], "policy": draft["policy"]}


PROBE = """import hashlib, json, os, subprocess
from pathlib import Path
source=Path(SOURCE)
receipt=Path(INPUT).read_text()
before=hashlib.sha256(source.read_bytes()).hexdigest()
execution=subprocess.run([PYTHON, str(source), INPUT, OUTPUT],
    capture_output=True, text=True, timeout=10)
output=Path(OUTPUT)
result={'uid':os.getuid(), 'receipt_read':receipt==RECEIPT,
    'output_written':execution.returncode==0 and json.loads(output.read_text())==EXPECTED,
    'parser_returncode':execution.returncode, 'parser_stderr':execution.stderr,
    'parser_sha256_before':before,
    'parser_sha256_after':hashlib.sha256(source.read_bytes()).hexdigest(),
    'private_mode':oct(Path(PRIVATE).stat().st_mode & 0o777)}
try:
    result['private_read']=Path(PRIVATE).read_text()=='FAKE_CANARY_SECRET'
except OSError as error:
    result.update(private_read=False, private_errno=error.errno)
print(json.dumps(result))
"""

METADATA_PATH = "/opt/skillguard-canary/metadata.txt"
ROOT_METADATA_PATH = "/opt/skillguard-canary/root-metadata.txt"
METADATA_PROBE = """import hashlib, json, os
from pathlib import Path
path=Path('/opt/skillguard-canary/metadata.txt')
before=path.stat()
result={'uid':os.getuid(), 'gid':os.getgid(), 'file_uid_before':before.st_uid,
    'file_gid_before':before.st_gid, 'mode_before':oct(before.st_mode & 0o777),
    'read_passed':path.read_text()=='FAKE_METADATA_CANARY'}
try:
    with path.open('r+b') as stream:stream.write(b'X')
    result['content_write_allowed']=True
except OSError as error:
    result.update(content_write_allowed=False, content_write_errno=error.errno)
try:
    os.chmod(path, 0o600)
    result['chmod_allowed']=True
except OSError as error:
    result.update(chmod_allowed=False, chmod_errno=error.errno)
try:
    os.chown(path, -1, os.getgid())
    result['chown_allowed']=True
except OSError as error:
    result.update(chown_allowed=False, chown_errno=error.errno)
after=path.stat()
result.update(file_uid_after=after.st_uid, file_gid_after=after.st_gid,
              mode_after=oct(after.st_mode & 0o777), content_after=path.read_text())
owned=Path('/opt/skillguard-canary/root-metadata.txt')
before=owned.stat()
parent=owned.parent.stat()
capabilities=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines()
                  if ':' in line)['CapEff'].strip()
control={'effective_uid':os.geteuid(), 'effective_gid':os.getegid(),
    'effective_capabilities':capabilities, 'file_uid_before':before.st_uid,
    'file_gid_before':before.st_gid, 'mode_before':oct(before.st_mode & 0o777),
    'parent_uid':parent.st_uid, 'parent_mode':oct(parent.st_mode & 0o777),
    'read_passed':owned.read_text()=='FAKE_ROOT_METADATA_CANARY'}
def write_owned():
    with owned.open('r+b') as stream:stream.write(b'X')
for name, operation in (
    ('content_write', write_owned), ('chmod', lambda:os.chmod(owned,0o600)),
    ('chown', lambda:os.chown(owned,-1,os.getgid()))):
    try:
        operation()
        control[name+'_allowed']=True
    except OSError as error:
        control.update({name+'_allowed':False,name+'_errno':error.errno})
after=owned.stat()
control.update(file_uid_after=after.st_uid, file_gid_after=after.st_gid,
               mode_after=oct(after.st_mode & 0o777), content_after=owned.read_text())
result['root_owned_control']=control
source=Path('/opt/skillguard-candidate/scripts/parse_receipt.py')
before=source.stat()
def source_sha():return hashlib.sha256(source.read_bytes()).hexdigest()
def directories():
    return {name:{'uid':path.stat().st_uid,'gid':path.stat().st_gid,
                  'mode':oct(path.stat().st_mode & 0o777)}
            for name,path in (('scripts',source.parent),('candidate',source.parent.parent))}
boundary={'parser_sha256_before':source_sha(), 'file_uid_before':before.st_uid,
    'file_gid_before':before.st_gid, 'mode_before':oct(before.st_mode & 0o777),
    'directories_before':directories()}
def write_source():
    with source.open('r+b') as stream:stream.write(b'X')
for name,operation in (
    ('content_write',write_source),('chmod',lambda:os.chmod(source,0o600)),
    ('chown',lambda:os.chown(source,-1,os.getgid())),
    ('unlink',lambda:os.unlink(source)),
    ('rename',lambda:os.rename(source,source.with_suffix('.fake'))),
    ('parent_chmod',lambda:os.chmod(source.parent,0o777)),
    ('root_chmod',lambda:os.chmod(source.parent.parent,0o777))):
    try:
        operation()
        boundary[name+'_allowed']=True
    except OSError as error:
        boundary.update({name+'_allowed':False,name+'_errno':error.errno})
after=source.stat()
boundary.update(parser_sha256_after=source_sha(),file_uid_after=after.st_uid,
    file_gid_after=after.st_gid,mode_after=oct(after.st_mode & 0o777),
    directories_after=directories())
result['candidate_source_control']=boundary
print(json.dumps(result))
"""


GUEST = """import copy, hashlib, json, pathlib, subprocess, sys
payload=json.loads(sys.stdin.read())
root=pathlib.Path('/root/skillguard-policy-'+payload['run_id']);root.mkdir(mode=0o700)
report={'outcomes':{}, 'sandboxes_stopped':{}}
def command(args, name, timeout=120):
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    (root/name).write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError(name+': native exit '+str(result.returncode))
    return result.stdout
try:
    dockerfile='FROM '+payload['image_id']+'''\nUSER root
RUN mkdir -p /opt/skillguard-canary
RUN printf FAKE_CANARY_SECRET > /opt/skillguard-canary/private.txt
RUN chmod 0644 /opt/skillguard-canary/private.txt && touch /sandbox/receipt-output.json
RUN chown 1000:1000 /sandbox/receipt-output.json
USER 1000:1000
WORKDIR /sandbox
'''
    (root/'Dockerfile').write_text(dockerfile)
    if payload.get('metadata_diagnostic'):
        metadata_layer='''RUN printf FAKE_METADATA_CANARY > /opt/skillguard-canary/metadata.txt
RUN chown 1000:0 /opt/skillguard-canary/metadata.txt
RUN chmod 0640 /opt/skillguard-canary/metadata.txt
RUN printf FAKE_ROOT_METADATA_CANARY > /opt/skillguard-canary/root-metadata.txt
RUN chown 0:0 /opt/skillguard-canary/root-metadata.txt
RUN chmod 0444 /opt/skillguard-canary/root-metadata.txt
RUN chown 0:0 /opt/skillguard-canary && chmod 0755 /opt/skillguard-canary
USER 1000:1000'''
        dockerfile=dockerfile.replace('USER 1000:1000', metadata_layer)
        (root/'Dockerfile').write_text(dockerfile)
    image='sg-receipt-policy:'+payload['run_id']
    command(['docker','build','-t',image,str(root)],'image-build.txt')
    image_id=command(['docker','image','inspect','--format','{{.Id}}',image],'image-id.txt').strip()
    report['image_id']=image_id
    archive=root/'image.tar'
    command(['docker','image','save','--output',str(archive),image_id],'image-save.txt')
    with archive.open('rb') as stream:
        report['image_archive_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
    for kind in ('permissive','restricted'):
        sandbox='sg-f'+kind[0]+'-'+payload['run_id']
        policy=copy.deepcopy(payload['policy'])
        if kind=='permissive':
            policy['filesystem_policy']['read_only'].append('/opt/skillguard-canary/private.txt')
        if payload.get('metadata_diagnostic'):
            permission='read_write' if kind=='permissive' else 'read_only'
            policy['filesystem_policy'][permission].append('/opt/skillguard-canary/metadata.txt')
            policy['filesystem_policy'][permission].append('/opt/skillguard-canary/root-metadata.txt')
        path=root/(kind+'-policy.json');path.write_text(json.dumps(policy))
        created=False
        try:
            command(['openshell','sandbox','create','--name',sandbox,'--from',image,
                '--policy',str(path),'--detach','--no-auto-providers','--','sleep','3600'],kind+'-create.txt')
            created=True
            ids=command(['docker','ps','-q','--filter',
                'label=openshell.ai/isolation-role=sandbox'],kind+'-container-ids.txt').split()
            containers=[json.loads(command(['docker','inspect',cid],
                kind+'-container-'+cid[:12]+'.json'))[0] for cid in ids]
            target=[c for c in containers if c['Name'].startswith(
                '/openshell-default--'+sandbox+'-')]
            if len(target)!=1 or target[0]['Image']!=image_id:
                raise RuntimeError('Native workload does not use the same prepared image')
            report[kind+'_container']={'id':target[0]['Id'],'image_id':target[0]['Image']}
            raw=command(['openshell','sandbox','exec','-n',sandbox,'--no-login-shell','--',
                'python','-c',payload['probe']],kind+'-probe.txt')
            report['outcomes'][kind]=json.loads(raw)
            native=json.loads(command(['openshell','sandbox','get',sandbox,'-o','json'],kind+'-native.json'))
            report[kind+'_native']=native
        finally:
            if created:
                command(['openshell','sandbox','stop',sandbox],kind+'-stop.txt')
                stopped=json.loads(command(['openshell','sandbox','get',sandbox,'-o','json'],kind+'-stopped.json'))
                report['sandboxes_stopped'][kind]=stopped.get('phase')=='Stopped'
except Exception as error:report['error']=str(error)
report['guest_artifacts']=str(root)
(root/'trial.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
"""


def run_trial(root: Path, preparation: Path, *, metadata_diagnostic: bool = False) -> dict:
    candidate_payload(root, preparation)  # Refuse changed/unknown source before native commands.
    parent = json.loads(preparation.read_text())
    store = ReviewStore(Path(parent["store"]))
    trial = validate_trial(store.get(parent["review_id"]))
    label = "metadata-policy" if metadata_diagnostic else "receipt-policy"
    folder = root / "results/integration" / f"{label}-{uuid.uuid4().hex[:8]}"
    folder.mkdir(mode=0o700)
    env = prepare_environment(root, "lima")
    report = {"run_id": folder.name, "candidate_sha256": parent["candidate_sha256"],
              "model_calls": 0,
              "complete": False, "activation_permitted": False,
              "scope": "Native same-image fake-file canary; no general runtime/agent coverage"}
    if metadata_diagnostic:
        report["scope"] = "Native fake metadata policy diagnostic; not candidate enforcement"

    def command(args, name, timeout=120):
        return recorded_command(args, root=root, env=env, output=folder/name, timeout=timeout)

    try:
        start = command(["limactl", "start", "--yes", "--timeout", "90s", "sgtrace-clean"],
                        "vm-start.txt")
        if start.returncode:
            raise RuntimeError("Native runner failed to start")
        setup = root / "scripts/linux_probe_setup_guest.sh"
        # Existing setup owns native mTLS readiness; no settings bypass or providers.
        import subprocess

        ready = subprocess.run(PREFIX + ["sh", "-s", "--", "sg-linux-trace-p0", "prepare-only"],
            input=setup.read_text(), capture_output=True, text=True, timeout=120, env=env)
        (folder/"gateway-setup.txt").write_text(ready.stdout+ready.stderr)
        if ready.returncode:
            raise RuntimeError("Existing native gateway setup failed")
        payload = trial | {"run_id": folder.name[-8:],
            "probe": "RECEIPT="+repr(RECEIPT)+"\nEXPECTED="+repr(EXPECTED)+"\n"
                "SOURCE='/opt/skillguard-candidate/scripts/parse_receipt.py'\n"
                "INPUT='/opt/skillguard-fixtures/input.txt'\n"
                "OUTPUT='/sandbox/receipt-output.json'\n"
                "PRIVATE='/opt/skillguard-canary/private.txt'\nPYTHON='python'\n"+PROBE}
        if metadata_diagnostic:
            payload.update(metadata_diagnostic=True, probe=METADATA_PROBE)
        body = "payload="+repr(json.dumps(payload))+"\n"+GUEST.replace(
            "payload=json.loads(sys.stdin.read())", "payload=json.loads(payload)")
        (folder/"native-guest.py").write_text(body)
        native = subprocess.run(PREFIX + ["python3", "-"], input=body, capture_output=True,
                                text=True, timeout=360, env=env)
        (folder/"transport-stderr.txt").write_text(native.stderr)
        (folder/"trial.json").write_text(native.stdout)
        if native.returncode:
            raise RuntimeError("Native file trial transport failed")
        result = json.loads(native.stdout)
        report["native_trial"] = result
        if result.get("error") or result.get("sandboxes_stopped") != {
                "permissive": True, "restricted": True}:
            raise RuntimeError(result.get("error", "Native sandbox cleanup unverified"))
        outcomes = result["outcomes"]
        if metadata_diagnostic:
            artifacts = {"trial.json": native.stdout.encode(),
                         "guest.py": body.encode(), "probe.py": METADATA_PROBE.encode()}
            report["artifacts"] = {name:digest(raw) for name, raw in artifacts.items()}
            diagnostic = store.record_metadata_policy_probe(parent["review_id"],
                report=json.dumps(report).encode(), artifacts=artifacts)
            report["metadata_policy_probe"] = diagnostic["data"]
        else:
            for value in outcomes.values():
                if any(value.get(k) != parent["parser_sha256"] for k in (
                        "parser_sha256_before", "parser_sha256_after")):
                    raise ValueError("Executed parser differs from archived source")
            # Existing verifier binds raw native policy + both real domain/denial results.
            enforcement = store.record_file_enforcement(parent["review_id"],
                executed_candidate_sha256=parent["candidate_sha256"],
                rootfs_sha256=result["image_archive_sha256"],
                native_policy=json.dumps(result["restricted_native"]).encode(),
                permissive_result=json.dumps(outcomes["permissive"]).encode(),
                restricted_result=json.dumps(outcomes["restricted"]).encode())
            report["file_enforcement"] = enforcement["data"]
    except Exception as error:
        report["error"] = str(error)
    finally:
        stop = command(["limactl", "stop", "--yes", "sgtrace-clean"], "vm-stop.txt", 60)
        if stop.returncode:
            command(["limactl", "stop", "--force", "sgtrace-clean"], "vm-force-stop.txt", 30)
        states = command(["limactl", "list", "--json"], "runner-states.json", 30)
        report["runner_states"] = {v["name"]:v["status"]
            for v in map(json.loads, states.stdout.splitlines())}
        report["runner_stopped"] = states.returncode == 0 and report["runner_states"].get(
            "sgtrace-clean") == "Stopped"
        report["decision"] = store.decide(parent["review_id"])
        report["candidate_unchanged"] = bool(candidate_payload(root, preparation))
        profile = preparation.parent / "staging-profile"
        pending = profile / "pending/skills" / f"{parent['native_pending_id']}.json"
        review = store.get(parent["review_id"])
        report["pending_preserved"] = (
            pending.is_file() and digest(pending.read_bytes()) == review["pending_sha256"])
        report["active_skill_absent"] = not (profile / "skills/receipt-organizer").exists()
        data = json.dumps(report, indent=2)+"\n"
        (folder/"enforcement.json").write_text(data)
        (root/f"results/{label}-latest.json").write_text(data)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--metadata-diagnostic", action="store_true")
    args = parser.parse_args()
    report = run_trial(Path(__file__).resolve().parents[1], args.preparation.resolve(),
                       metadata_diagnostic=args.metadata_diagnostic)
    print(json.dumps({k:report.get(k) for k in (
        "run_id", "error", "runner_stopped", "candidate_unchanged", "pending_preserved",
        "active_skill_absent", "decision")}, indent=2))
    if report.get("error") or not report["runner_stopped"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
