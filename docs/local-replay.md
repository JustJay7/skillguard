# Local isolation verification

Verified on 2026-09-29: OpenShell v0.1.2, Apple Silicon MicroVM, Python 3.12.14
inside the guest. Local gateway uses `compute_driver = "vm"`, `vcpus = 2`,
`mem_mib = 2048`. The official Homebrew installer also required a separate
`brew install e2fsprogs` before it could format the VM disk.

## Reproduce the controlled probes

Prepare a bundle containing code and fake fixtures only:

```sh
mkdir -p ../work/replay/results
cp -R skillguard scripts skills ../work/replay/
openshell sandbox create --name skillguard-probe --from python:3.12-slim --detach --no-auto-providers --label project=skillguard -- sleep 3600
openshell settings set skillguard-probe --key ocsf_json_enabled --value true
openshell sandbox upload skillguard-probe ../work/replay /sandbox/replay
openshell sandbox exec -n skillguard-probe --workdir /sandbox/replay/replay --no-login-shell -- python -m scripts.local_smoke
openshell sandbox exec -n skillguard-probe --workdir /sandbox/replay/replay --no-login-shell -- python -m scripts.process_probe
openshell sandbox download skillguard-probe replay/replay/results results/openshell
openshell logs skillguard-probe -n 300 > results/openshell-logs.txt
openshell sandbox stop skillguard-probe
```

For an existing retained sandbox, use `openshell sandbox start skillguard-probe`
instead of create. The initial name `skillguard-phase0-vm` was rejected because
OpenShell limits names to 19 characters. The image tag is not yet digest-pinned;
record the resolved image before using this as a benchmark harness.

The smoke probe asserts actual receipt of the fake canary. It gives both runs
the same import state and output path so interpreter cold-start noise does not
masquerade as skill behavior. It does not filter away observed paths.

## Policy results

| Experiment | Observed result | Evidence |
| --- | --- | --- |
| Inspect effective policy | Sandbox-scoped | `results/openshell-policy.json` |
| Remove `/tmp` write permission live | Rejected | `results/static-policy-enforcement.txt` |
| Add `/var/tmp` write permission live | Update acknowledged; actual writes still denied with errno 13 | `results/filesystem-{before,after}.json`, `results/filesystem-addition-update.txt` |
| Add loopback proxy rule | Rejected as always-blocked destination | `results/network-policy-update.txt` |
| Add `skillguard-canary.invalid:8765` for Python | Loaded without recreating sandbox; no traffic sent | `results/network-policy-update-invalid-domain.txt` |

The filesystem results show that a running process does not gain expanded
static access from a live update. Release source says additive filesystem paths
take effect on the next restart (`openshell-server/src/grpc/validation.rs`).
Restart behavior has not been tested here. A successful update response alone
does not prove that permission changed.

## Limits

- Python audit hooks run inside the evaluated interpreter, can be evaded by
  hostile code, and include attempted operations. These probes establish
  controlled-fixture observability inside isolation, not complete monitoring.
- The process probe is separate from the invoice skill; do not attribute its
  `/bin/echo` event to the planted invoice behavior.
- Native supervisor logging reported that `/var/log` was unavailable and used
  stderr. OCSF JSONL export remains unresolved; only shorthand logs were saved.
- In-VM localhost traffic is different from proxy-mediated external traffic.
- No model-generated invoice injection, automatic approval, benchmark, or
  real-secret exfiltration is claimed.
