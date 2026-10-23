The JSONL fixture contains 16 actual metadata events from the controlled Linux
Sysdig 0.41.4 capture c3, with completed file I/O, exec and connect records only.
Source: private `results/integration/kernel-c3/c3-workload.jsonl`, bound to the
container in `results/integration/strace-e019707b/container.json`.

It includes the escaped child's completed 26-byte fake write at event 621311,
which strace missed, and the refused connect whose destination is unresolved.
No I/O payloads, program arguments, environment values or credentials are included.
These are fixed integration events, not a skill benchmark or complete trace.
