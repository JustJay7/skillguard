"""Trusted VM controller for the installed Harbor Terminus agent, never a harness.

SDK credential arrives in memory on stdin. No credential in process environment,
task files, agent options or container. Offline mode uses scripted HTTP responses
and must never count as model performance or resistance evidence.
"""
from __future__ import annotations

import asyncio
import contextlib
import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
import time
import traceback
from pathlib import Path

import httpx

from skillguard.models.bounded_transport import MODEL, AgentCallBudget, probe_request_limit
from skillguard.models.harbor_transport import native_harbor_client
from skillguard.models.recorded_responses import RecordedResponses

FAKE_KEY = 'skillguard-sdk-fake-confinement-only-20261006'
PARSER = '/workspace/skills/receipt-organizer/scripts/parse_receipt.py'


def confinement(container: dict, root: Path, key: str, sandbox: str | None = None) -> dict:
    host = container['HostConfig']
    mounts = container.get('Mounts', [])
    safe_mounts = all(m['Source'].startswith(str(root / 'jobs') + '/')
                      and m['Destination'].startswith('/logs/') for m in mounts)
    proof_script = '''import hashlib,json,os,pathlib
target=HASH
def visible(path):
 try: return pathlib.Path(path).exists()
 except PermissionError: return False
matches=[]; inspected=0; denied=0
for kind in ('environ','cmdline'):
 for path in pathlib.Path('/proc').glob('[0-9]*/'+kind):
  try:
   data=path.read_bytes(); inspected+=1
   for value in data.split(bytes([0])):
    for candidate in (value,value.partition(b'=')[2]):
     if hashlib.sha256(candidate).hexdigest()==target: matches.append(str(path))
  except (PermissionError,ProcessLookupError,FileNotFoundError): denied+=1
print(json.dumps({'uid':os.getuid(),'fake_key_matches':matches,
 'proc_files_inspected':inspected,'proc_files_denied':denied,
 'controller_root_visible':visible(ROOT),
 'docker_socket_visible':visible('/var/run/docker.sock')}))
'''.replace('HASH', repr(hashlib.sha256(key.encode()).hexdigest())).replace(
            'ROOT', repr(str(root)))
    result = subprocess.run(['docker', 'exec', '-i', '--user', '1000:1000',
        container['Id'], 'python3', '-'], input=proof_script, capture_output=True,
        text=True, check=True, timeout=20)
    proof = json.loads(result.stdout)
    proof.update(network_mode=host['NetworkMode'], pid_mode=host.get('PidMode'),
        privileged=host['Privileged'], cap_add=host.get('CapAdd'), mounts_safe=safe_mounts,
        credential_in_container_config=key in json.dumps(container))
    if sandbox:
        scope = '''import errno,json,os,pathlib
result={'uid':os.getuid(),'capabilities':next(l.split(':')[1].strip()
 for l in pathlib.Path('/proc/self/status').read_text().splitlines() if l.startswith('CapEff:'))}
try:
 pathlib.Path('/opt/fake/private-note.txt').read_bytes();result['private_read_denied']=False
except OSError as error:
 result['private_read_denied']=error.errno==errno.EACCES
print(json.dumps(result))
'''
        result = subprocess.run(['openshell', 'sandbox', 'exec', '--name', sandbox,
            '--no-tty', '--no-login-shell', '--timeout', '20', '--', 'python3', '-c', scope],
            capture_output=True, text=True, check=True, timeout=30)
        effective = json.loads(result.stdout)
        stat = subprocess.run(['docker', 'exec', '--user', 'root', container['Id'],
            'python3', '-c', "import json,os; p='/opt/fake/private-note.txt'; s=os.stat(p);"
            "print(json.dumps({'mode':oct(s.st_mode&511),'size':s.st_size,'uid':s.st_uid}))"],
            capture_output=True, text=True, check=True, timeout=20)
        source = json.loads(stat.stdout)
        proof.update(runtime='openshell', effective_scope=effective, private_file_control=source)
        proof['passed'] = (proof['uid'] == effective['uid'] == 1000
            and effective['capabilities'] == '0000000000000000'
            and effective['private_read_denied'] and source['mode'] == '0o444'
            and source['size'] == 25 and source['uid'] == 0
            and not proof['fake_key_matches'] and proof['proc_files_inspected'] > 0
            and not proof['controller_root_visible'] and not proof['docker_socket_visible']
            and not host.get('PidMode') and not host['Privileged']
            and not proof['credential_in_container_config']
            and all(not m['Source'].startswith(str(root) + '/') for m in mounts))
        return proof
    proof['passed'] = (proof['uid'] == 1000 and not proof['fake_key_matches']
        and proof['proc_files_inspected'] > 0 and not proof['controller_root_visible']
        and not proof['docker_socket_visible'] and safe_mounts
        and host['NetworkMode'] == 'none' and not host.get('PidMode')
        and not host['Privileged'] and not host.get('CapAdd')
        and not proof['credential_in_container_config'])
    return proof


async def execute(root: Path, header: dict):
    if header['mode'] not in {'live', 'offline', 'recorded'}:
        raise ValueError('Unknown controller mode')
    offline = header['mode'] != 'live'
    limit = probe_request_limit(header.get('maximum_model_requests', 4),
                                header.get('app_execution_profile'))
    if limit == 8 and not (header.get('runtime') == 'openshell'
            and header.get('capture_native') is True
            and header.get('frontmatter_compat') is True
            and header.get('native_skill_discovery') is True):
        raise ValueError('Eight-request app controller requires native captured skill use')
    budget = AgentCallBudget(root / 'cost.csv', root / 'responses', max_calls=limit,
                             total_limit_usd=header.get('aggregate_cap_usd', .75),
                             reservation_profile=header.get('reservation_profile', 'legacy'))
    requests = []
    state = {'confinement_passed': False}

    def mock_response(request):
        if not state['confinement_passed']:
            raise ValueError('Native sandbox confinement was not verified')
        payload = json.loads(request.read())
        if header['api_key'] in json.dumps(payload):
            raise ValueError('SDK key entered model messages')
        requests.append(payload)
        (root / 'requests.json').write_text(json.dumps(requests, indent=2))
        command = ("python3 - <<'PY'\nimport json,subprocess\nfrom pathlib import Path\n"
            "p=Path('/workspace/out'); p.mkdir(exist_ok=True)\n"
            "(p/'input.txt').write_text('Mock Grocery\\nDate: 2026-10-04\\n"
            "Subtotal: 20.00\\nTax: 3.00\\nTotal paid: 23.00\\n')\n"
            f"subprocess.run(['python3','{PARSER}',str(p/'input.txt'),"
            "str(p/'parsed.json')],check=True)\n"
            "receipt=json.loads((p/'parsed.json').read_text())\n"
            "(p/'answer.json').write_text(json.dumps({'route':'receipt',"
            "'receipt':receipt,'clarification_fields':[],'question':None}))\n"
            "print('OFFLINE SCRIPTED HARNESS CHECK ONLY')\nPY\n")
        if header.get('instruction_protocol'):
            command = ("python3 - <<'PY'\nimport json,subprocess\nfrom pathlib import Path\n"
                "p=Path('/workspace/out');p.mkdir(exist_ok=True)\n"
                f"subprocess.run(['python3','{PARSER}','/workspace/input/receipt.txt',"
                "str(p/'parsed.json')],check=True)\n"
                "receipt=json.loads((p/'parsed.json').read_text())\n"
                "(p/'answer.json').write_text(json.dumps({'route':'receipt','receipt':receipt,"
                "'clarification_fields':[],'question':None}))\n"
                "print('OFFLINE SCRIPTED HARNESS CHECK ONLY')\nPY\n")
        if header.get('learning_trial') or header.get('security_trial'):
            contract = json.loads((root / 'task/tests/contract.json').read_text())
            reference = {**contract['expected'], 'question': (
                'Please clarify missing values?' if contract['ask'] else None)}
            command = ("python3 - <<'PY'\nfrom pathlib import Path\n"
                "p=Path('/workspace/out');p.mkdir(exist_ok=True)\n"
                "(p/'answer.json').write_text(" + repr(json.dumps(reference)) + ")\n"
                "print('OFFLINE WIRING CONTROL ONLY')\nPY\n")
        answer = {'analysis': 'Scripted offline integration check; no model inference.',
                  'plan': 'Run the frozen parser and write the calibration answer.',
                  'commands': [{'keystrokes': command, 'duration': 1.0}],
                  'task_complete': True}
        response = {'id': 'offline-scripted', 'created': 0,
            'object': 'chat.completion', 'model': MODEL,
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': json.dumps(answer)}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30}}
        return httpx.Response(200, content=gzip.compress(json.dumps(response).encode()),
            headers={'content-encoding': 'gzip', 'content-type': 'application/json'})

    class CheckedUpstream(httpx.BaseTransport):
        def __init__(self):
            self.inner = (RecordedResponses(root / 'recorded') if header['mode'] == 'recorded'
                          else httpx.MockTransport(mock_response) if offline
                          else httpx.HTTPTransport(retries=0))
            if header['mode'] == 'live':
                # Check trusted-controller egress before spending a model allowance.
                # The workload remains network-isolated. This public GET has no key.
                with httpx.Client(timeout=10, trust_env=False) as ready:
                    for attempt in range(3):
                        try:
                            response = ready.get('https://api.tokenfactory.nebius.com/docs')
                            response.raise_for_status()
                            (root / 'controller-network-ready.json').write_text(json.dumps({
                                'public_https_ready': True, 'attempts': attempt + 1,
                                'inference_requests': 0, 'credential_sent': False}))
                            break
                        except httpx.HTTPError:
                            if attempt == 2:
                                raise
                            time.sleep(1)

        def handle_request(self, request):
            if not state['confinement_passed']:
                raise ValueError('Confinement proof missing before inference')
            payload = json.loads(request.read())
            if header.get('security_trial'):
                from skillguard.evaluation.security_probe import verify_request

                design = (root / 'task/security-design.json').read_bytes()
                verify_request([payload], design, (root / 'task/instruction.md').read_bytes(),
                    (root / 'task/environment/input/receipt.txt').read_bytes(),
                    header['security_trial'], json.loads(design)['candidate_sha256'])
            if header.get('learning_trial'):
                from skillguard.evaluation.receipt_learning import verify_request

                verify_request(payload, with_skill=header['native_skill_discovery'],
                    protocol=header['learning_trial'].get('protocol',
                                                         'receipt-learning-holdout-v1'))
            if header.get('instruction_protocol'):
                from skillguard.evaluation.agent_task_protocol import (
                    SUPPORTED_PROTOCOLS,
                    verify_instruction,
                )

                if header['instruction_protocol'] not in SUPPORTED_PROTOCOLS:
                    raise ValueError('Unsupported trusted instruction protocol')
                verify_instruction([payload], (root / 'task/instruction.md').read_bytes(),
                    (root / 'task/environment/input/receipt.txt').read_bytes(),
                    header['instruction_protocol'])
            if header['api_key'] in json.dumps(payload):
                raise ValueError('SDK key entered model messages')
            if header['mode'] != 'offline':
                requests.append(payload)
                (root / 'requests.json').write_text(json.dumps(requests, indent=2))
            return self.inner.handle_request(request)

        def close(self):
            self.inner.close()

    capture = None
    if header.get('capture_native'):
        from scripts.native_agent_capture import NativeAgentCapture

        capture = NativeAgentCapture(root, header['event_format'], header.get('runtime', 'docker'),
                                    receipt_artifacts=header.get('require_skill_use_proof') is True)
    try:
        if capture:
            capture.start()
        from scripts.native_harbor_compat import frontmatter_compat

        with frontmatter_compat(header.get('frontmatter_compat', False)) as compatibility:
            if compatibility:
                (root / 'frontmatter-compat.json').write_text(json.dumps(compatibility, indent=2))
            return await execute_job(root, header, budget, state, CheckedUpstream, capture)
    finally:
        if capture:
            capture.finish()


async def execute_job(root, header, budget, state, upstream_class, capture):
    from harbor.job import Job
    from harbor.models.job.config import JobConfig

    offline = header['mode'] != 'live'
    runtime = header.get('runtime', 'docker')
    if runtime not in {'docker', 'openshell'}:
        raise ValueError('Unsupported native runtime')
    async with native_harbor_client(budget, api_key=header['api_key'],
                                   authorized_limit_usd=header.get('aggregate_cap_usd', .75),
            app_execution_profile=header.get('app_execution_profile'),
            upstream=upstream_class(), compatibility_probe=(runtime == 'openshell'
                and header.get('frontmatter_compat') is True
                and (header.get('native_skill_discovery') is True
                     or bool(header.get('learning_trial'))))) as options:
        environment = {'type': 'docker', 'delete': True, 'env': {}}
        if runtime == 'openshell':
            from skillguard.review.snapshot import artifact_tree_digest

            environment = {'type': None,
                'import_path': 'scripts.harbor_openshell_environment:ReceiptOpenShellEnvironment',
                'delete': True, 'env': {}, 'kwargs': {'expected_environment_sha256':
                    artifact_tree_digest(root / 'task/environment')}}
        artifacts = ['/workspace/out']
        if not header.get('learning_trial') or header.get('native_skill_discovery'):
            artifacts.append(PARSER)
        if header.get('learning_trial'):
            artifacts += ['/workspace/input/receipt.txt']
        if header.get('require_skill_use_proof'):
            artifacts += ['/workspace/skills/receipt-organizer/SKILL.md',
                          '/workspace/input/receipt.txt']
        artifacts = list(dict.fromkeys(artifacts))
        config = JobConfig.model_validate({'job_name': 'receipt-probe',
            'jobs_dir': str(root / 'jobs'), 'n_attempts': 1, 'n_concurrent_trials': 1,
            'quiet': True, 'retry': {'max_retries': 0},
            'environment': environment,
            'agents': [{'name': 'terminus-2', 'model_name': 'openai/' + MODEL,
                'env': {}, 'kwargs': {'max_turns': header.get('maximum_model_requests', 4),
                    'enable_summarize': False,
                    'record_terminal_session': False, 'temperature': 0,
                    'api_base': 'https://api.tokenfactory.nebius.com/v1',
                    'llm_kwargs': options}}],
            'tasks': [{'path': str(root / 'task')}],
            'artifacts': artifacts})
        job = await Job.create(config)

        async def on_agent_start(event):
            ids = subprocess.check_output(['docker', 'ps', '-q'], text=True).split()
            containers = json.loads(subprocess.check_output(['docker', 'inspect', *ids]))
            sandbox = None
            if runtime == 'openshell':
                paths = list((root / 'jobs').rglob('openshell/binding.json'))
                if len(paths) != 1:
                    raise ValueError('Expected one native OpenShell binding')
                binding = json.loads(paths[0].read_text())
                selected = [c for c in containers if c['Id'] == binding['container_id']]
                sandbox = binding['sandbox']
            else:
                selected = [c for c in containers if any(
                    m['Source'].startswith(str(root / 'jobs') + '/') for m in c.get('Mounts', []))]
            if len(selected) != 1:
                raise ValueError('Expected one native trial container')
            if capture:
                capture.container_id = selected[0]['Id']
            proof = confinement(selected[0], root, header['api_key'], sandbox)
            (root / 'confinement.json').write_text(json.dumps(proof, indent=2))
            (root / 'container-inspect.json').write_text(json.dumps(selected[0], indent=2))
            if not proof['passed']:
                raise ValueError('Native container credential boundary failed')
            if (header.get('instruction_protocol') or header.get('learning_trial')
                    or header.get('security_trial')):
                code = ("import hashlib,json;from pathlib import Path;"
                    "p=Path('/workspace/input/receipt.txt');"
                    "print(json.dumps({'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),"
                    "'bytes':p.stat().st_size}))")
                result = subprocess.run(['openshell', 'sandbox', 'exec', '--name', sandbox,
                    '--no-tty', '--no-login-shell', '--timeout', '20', '--', 'python3', '-c', code],
                    capture_output=True, text=True, check=True, timeout=30)
                materialized = json.loads(result.stdout)
                expected = (root / 'task/environment/input/receipt.txt').read_bytes()
                if (materialized['sha256'] != hashlib.sha256(expected).hexdigest()
                        or materialized['bytes'] != len(expected)):
                    raise ValueError('Native receipt input differs before inference')
                (root / 'input-proof.json').write_text(json.dumps(materialized))
            if header.get('learning_trial'):
                code = ("import hashlib,json;from pathlib import Path;"
                    "p=Path('/workspace/skills');"
                    "files={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() "
                    "for f in sorted(p.rglob('*')) if f.is_file()};print(json.dumps(files))")
                result = subprocess.run(['openshell', 'sandbox', 'exec', '--name', sandbox,
                    '--no-tty', '--no-login-shell', '--timeout', '20', '--', 'python3', '-c', code],
                    capture_output=True, text=True, check=True, timeout=30)
                files = json.loads(result.stdout)
                expected = root / 'task/environment/skills'
                wanted = {str(f.relative_to(expected)):hashlib.sha256(f.read_bytes()).hexdigest()
                          for f in sorted(expected.rglob('*')) if f.is_file()}
                if files != wanted or bool(files) != header['native_skill_discovery']:
                    raise ValueError('Native skill exposure differs from frozen arm')
                (root / 'skill-exposure.json').write_text(json.dumps(files))
            state['confinement_passed'] = True

        job.on_agent_started(on_agent_start)
        result = await job.run()
        (root / 'job-summary.json').write_text(result.model_dump_json(indent=2))
    return {'mode': header['mode'], 'model_requests': budget.calls if not offline else 0,
            'mock_http_requests': budget.calls if offline else 0,
            'confinement_passed': state['confinement_passed']}


def main():
    root = Path(sys.argv[1])
    header = json.loads(sys.stdin.buffer.readline())
    root.mkdir(mode=0o700)
    with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as archive:
        archive.extractall(root, filter='data')
    result = {'mode': header['mode']}
    with ((root / 'controller-log.txt').open('w') as log,
          contextlib.redirect_stdout(log), contextlib.redirect_stderr(log)):
        try:
            result.update(asyncio.run(execute(root, header)))
        except Exception as error:
            # Exception text may include SDK details; only persist its type.
            result['error_type'] = type(error).__name__
            if header['mode'] != 'live':
                result['offline_error'] = ''.join(traceback.format_exception(error)).replace(
                    header['api_key'], '[fake key withheld]')
    (root / 'controller-result.json').write_text(json.dumps(result, indent=2))
    # Fail closed rather than export a credential accidentally serialized upstream.
    for path in root.rglob('*'):
        if path.is_file() and header['api_key'].encode() in path.read_bytes():
            raise RuntimeError('Credential found in native output; export withheld')
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
        for name in ('jobs', 'responses', 'cost.csv', 'requests.json', 'confinement.json',
                     'container-inspect.json', 'job-summary.json', 'controller-log.txt',
                     'controller-result.json', 'recorded', 'capture', 'frontmatter-compat.json',
                     'input-proof.json', 'skill-exposure.json', 'controller-network-ready.json'):
            if (root / name).exists():
                archive.add(root / name, arcname=name)


if __name__ == '__main__':
    main()
