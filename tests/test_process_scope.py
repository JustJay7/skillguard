import json

import pytest

from skillguard.traces.process_scope import compare_parser_to_control

CONTAINER = "a" * 64


def row(number, pid, start, kind="read", *, parent=(10, 100), path="/input.txt", arg=None):
    return {
        "container.id": CONTAINER[:12], "container.full_id": CONTAINER,
        "evt.num": number, "evt.rawtime": 1000 + number, "evt.type": kind,
        "evt.dir": ">" if kind == "procexit" else "<",
        "evt.rawres": 0 if kind == "execve" else 10,
        "proc.pid": pid, "proc.pid.ts": start,
        "proc.ppid": parent[0], "proc.ppid.ts": parent[1],
        "thread.tid": pid, "proc.exepath": "/usr/local/bin/python3.12",
        "proc.args[0]": arg, "fd.type": "file", "fd.name": path,
    }


def capture():
    return [
        row(1, 10, 100, "execve", arg="/opt/skillguard-launch.py", parent=(1, 1)),
        row(2, 20, 200, "execve", arg="/opt/skillguard-baseline.py"),
        row(3, 20, 200, path="/runtime.py"),
        row(4, 20, 200, "procexit"),
        row(5, 30, 300, "execve", arg="/opt/skillguard-candidate/scripts/parse_receipt.py"),
        row(6, 30, 300, path="/runtime.py"),
        row(7, 30, 300, path="/input.txt"),
        row(8, 30, 300, "write", path="/output.json"),
        # Native ancestry ties this child to the candidate, even after root exits.
        row(9, 40, 400, "execve", parent=(30, 300), arg="/child.py"),
        row(10, 30, 300, "procexit"),
        row(11, 40, 400, "write", parent=(1, 1), path="/child-output.txt"),
        row(12, 40, 400, "procexit", parent=(1, 1)),
        # PID reused after candidate exit is a different native identity.
        row(13, 30, 1300, path="/operator-secret.txt"),
        row(14, 50, 500, path="/operator-probe.txt"),
        # A reused parent PID cannot give an unrelated child candidate ancestry.
        row(15, 60, 600, path="/unrelated.txt", parent=(30, 1300)),
    ]


def compare(rows):
    return compare_parser_to_control("\n".join(json.dumps(r) for r in rows),
                                     container_id=CONTAINER)


def test_native_process_tree_excludes_operator_and_pid_reuse_and_keeps_orphan_child():
    result = compare(capture())
    assert result["diff"]["added"]["files_read"] == ["/input.txt"]
    assert result["diff"]["added"]["files_written"] == ["/child-output.txt", "/output.json"]
    assert result["after"]["files_read"] == ["/input.txt", "/runtime.py"]
    assert result["after_event_references"]["files_written:/child-output.txt"] == ["sysdig:11"]
    assert result["after_processes"] == [[30, 300], [40, 400]]
    assert result["complete"] is False
    assert result["baseline_kind"] == "empty_python_control"


def test_foreign_short_id_cannot_change_selected_process_ancestry_or_lifetime():
    rows = capture()
    foreign = row(6, 99, 9900, 'execve', arg='/foreign.py', parent=(30, 300))
    foreign['container.id'] = 'foreign'
    assert compare(rows + [foreign]) == compare(rows)


def test_file_object_observations_do_not_collapse_distinct_paths_in_process_diff():
    rows = capture()
    for r in rows:
        if r['evt.type'] in {'read', 'write'}:
            r.update({'fd.num': 3, 'fd.dev.major': 0, 'fd.dev.minor': 42, 'fd.ino': 77})
    result = compare_parser_to_control('\n'.join(json.dumps(r) for r in rows),
        container_id=CONTAINER, include_file_identity=True)
    identities = result['after_file_identity_analysis']
    assert identities['reported_identity_matches']
    assert result['after']['files_read'] == ['/input.txt', '/runtime.py']
    assert result['file_identity_included'] is True
    assert result['after_unresolved_events']
    assert identities['path_permissions_canonicalized'] is False


def test_file_identity_uncertainty_does_not_replace_an_existing_access_gap():
    rows = capture()
    rows[5].update({'evt.type': 'openat', 'evt.rawres': 3, 'fd.num': 3,
                    'fd.dev.major': 0, 'fd.dev.minor': 42, 'fd.ino': 77})
    result = compare_parser_to_control('\n'.join(json.dumps(r) for r in rows),
        container_id=CONTAINER, include_file_identity=True)
    gap = result['after_unresolved_events']['sysdig:6']
    assert 'flags' in gap and 'unresolved' in gap
    assert 'inode generation' in gap


@pytest.mark.parametrize('page_size,address', [(None, '2000'), (4096, '2000'), (4096, '9000')])
def test_mapping_upgrade_never_claims_completed_file_write(page_size, address):
    from tests.test_mapping_regions import call

    rows = capture()
    calls = call(1, pid=30, ts=300, tid=30, length='4096', path='/fake/shared-map')
    calls += call(3, 'mprotect', pid=30, ts=300, tid=30, address=address,
                  length='4096', result=0, prot='PROT_READ|PROT_WRITE')
    rows = rows[:5] + calls + rows[5:]
    for number, event in enumerate(rows, 1):
        event['evt.num'] = number
        event['evt.rawtime'] = number * 100
    result = compare_parser_to_control('\n'.join(json.dumps(r) for r in rows),
                                       container_id=CONTAINER, page_size=page_size)
    resolved = page_size == 4096 and address == '2000'
    assert bool(result['after_unresolved_events']) is not resolved
    assert ('/fake/shared-map' in result['after_mapping_capabilities']['files_written']) is resolved
    assert '/fake/shared-map' not in result['after']['files_written']
    assert result['complete'] is False


@pytest.mark.parametrize("missing", [2, 4, 5, 10, 12])
def test_missing_exec_or_process_exit_cannot_form_bounded_comparison(missing):
    with pytest.raises(ValueError):
        compare([r for r in capture() if r["evt.num"] != missing])


def test_ambiguous_candidate_start_is_refused():
    rows = capture() + [row(16, 70, 700, "execve",
                           arg="/opt/skillguard-candidate/scripts/parse_receipt.py")]
    with pytest.raises(ValueError, match="unique"):
        compare(rows)


def test_missing_start_identity_on_candidate_activity_is_refused():
    rows = capture()
    rows[6]["proc.pid.ts"] = None
    with pytest.raises(ValueError, match="identity"):
        compare(rows)


def test_control_and_candidate_must_have_same_native_launcher_parent():
    rows = capture()
    rows[4]["proc.ppid.ts"] = 999
    with pytest.raises(ValueError, match="launcher"):
        compare(rows)


def test_selected_process_activity_after_exit_is_refused():
    with pytest.raises(ValueError, match="lifetime"):
        compare(capture() + [row(16, 30, 300, path="/late.txt")])
