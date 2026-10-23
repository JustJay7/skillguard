import json

import pytest

from skillguard.review.snapshot import digest
from tests.test_candidate_execution_review import fixture
from tests.test_process_scope import capture, compare


def setup(tmp_path, rows=None):
    store, rid, report, artifacts = fixture(tmp_path)
    rows = capture() if rows is None else rows
    comparison = compare(rows)
    container = json.loads(artifacts["container.json"])
    for row in rows:
        row["container.id"] = container["id"][:12]
        row["container.full_id"] = container["id"]
    image = json.loads(artifacts["candidate-image.json"])
    artifacts["candidate-image.json"] = json.dumps(image | {
        "control_kind": "empty_python_control", "control_sha256": digest(b"pass\n"),
        "launcher_sha256": "b" * 64,
    }).encode()
    artifacts["workload.jsonl"] = "\n".join(json.dumps(r) for r in rows).encode()
    artifacts["process-comparison.json"] = json.dumps(comparison).encode()
    report["artifacts"] = {name: digest(raw) for name, raw in artifacts.items()}
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    return store, rid, report, artifacts, comparison


def test_comparison_is_recomputed_archived_and_does_not_approve(tmp_path):
    store, rid, report, artifacts, comparison = setup(tmp_path)
    store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    current = store.get(rid)["latest"]["candidate_process_comparison"]
    assert current["diff"] == comparison["diff"]
    assert current["complete"] is False
    assert store.evidence(rid)["E9"]["value"]["baseline_kind"] == "empty_python_control"
    assert store.decide(rid)["activation_permitted"] is False
    # No actual input/output record values are included in model evidence.
    assert "candidate-execution.json" not in json.dumps(store.evidence(rid))


def ipc_setup(tmp_path):
    rows = capture()
    rows[6].update({'fd.type': 'pipe', 'fd.num': 5, 'fd.name': ''})
    return setup(tmp_path, rows)


def test_ipc_records_and_unresolved_peers_survive_review_reopen(tmp_path):
    store, rid, report, artifacts, comparison = ipc_setup(tmp_path)
    store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    from skillguard.review.store import ReviewStore

    reopened = ReviewStore(store.root)
    evidence = reopened.evidence(rid)['E9']['value']
    assert evidence['after_socket_io'] == comparison['after_socket_io']
    assert len(evidence['after_socket_io']) == 1
    assert 'sysdig:7' in evidence['after_unresolved_events']
    assert reopened.decide(rid)['activation_permitted'] is False


def test_socket_bytes_cannot_be_forged_by_replacing_comparison_attachment(tmp_path):
    store, rid, report, artifacts, comparison = ipc_setup(tmp_path)
    comparison['after_socket_io'][0]['bytes_transferred'] = 1000
    artifacts['process-comparison.json'] = json.dumps(comparison).encode()
    report['artifacts'] = {name: digest(raw) for name, raw in artifacts.items()}
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    with pytest.raises(ValueError, match='native process evidence'):
        store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def test_mapping_page_size_cannot_be_added_without_hash_bound_native_control(tmp_path):
    store, rid, report, artifacts, comparison = setup(tmp_path)
    comparison['mapping_region_page_size'] = 4096
    artifacts['process-comparison.json'] = json.dumps(comparison).encode()
    report['artifacts'] = {name: digest(raw) for name, raw in artifacts.items()}
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    with pytest.raises(ValueError, match='page size lacks native fixture binding'):
        store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def test_file_identity_cannot_be_enabled_without_bound_positive_controls(tmp_path):
    store, rid, report, artifacts, comparison = setup(tmp_path)
    comparison['file_identity_included'] = True
    artifacts['process-comparison.json'] = json.dumps(comparison).encode()
    report['artifacts'] = {name: digest(raw) for name, raw in artifacts.items()}
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    with pytest.raises(ValueError, match='file identity lacks native fixture binding'):
        store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def identity_setup(tmp_path):
    from skillguard.traces.process_scope import compare_parser_to_control
    from tests.test_native_file_identity import fixture as native_fixture

    text, source = native_fixture()
    rows = capture()
    for r in rows:
        if r['evt.type'] in {'read', 'write'}:
            r.update({'fd.num': 3, 'fd.dev.major': 0, 'fd.dev.minor': 42, 'fd.ino': 77})
    rows += [json.loads(line) for line in text.splitlines()]
    store, rid, report, artifacts, _ = setup(tmp_path, rows)
    container = json.loads(artifacts['container.json'])['id']
    comparison = compare_parser_to_control(artifacts['workload.jsonl'].decode(),
        container_id=container, include_file_identity=True)
    artifacts['probe-console.json'] = json.dumps({'workload_checks': {
        'file_identity_checks': source['file_identity_checks']}}).encode()
    artifacts['process-comparison.json'] = json.dumps(comparison).encode()
    report['artifacts'] = {name: digest(raw) for name, raw in artifacts.items()}
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    return store, rid, report, artifacts, comparison


def test_bound_file_identity_survives_reopen_without_alias_permission_grants(tmp_path):
    store, rid, report, artifacts, comparison = identity_setup(tmp_path)
    store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    from skillguard.review.store import ReviewStore

    reopened = ReviewStore(store.root)
    evidence = reopened.evidence(rid)['E9']['value']
    assert evidence['file_identity_included'] is True
    assert evidence['after_file_identity_analysis'] == comparison['after_file_identity_analysis']
    assert evidence['after_file_identity_analysis']['path_permissions_canonicalized'] is False
    assert reopened.decide(rid)['activation_permitted'] is False


def test_forged_inode_cannot_replace_native_identity_even_with_new_manifest(tmp_path):
    store, rid, report, artifacts, comparison = identity_setup(tmp_path)
    comparison['after_file_identity_analysis']['observations'][0]['object_identity']['inode'] += 1
    artifacts['process-comparison.json'] = json.dumps(comparison).encode()
    report['artifacts'] = {name: digest(raw) for name, raw in artifacts.items()}
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    with pytest.raises(ValueError, match='native process evidence'):
        store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def test_changed_diff_is_refused_even_if_caller_updates_manifest(tmp_path):
    store, rid, report, artifacts, comparison = setup(tmp_path)
    comparison["diff"]["added"]["files_read"] = []
    artifacts["process-comparison.json"] = json.dumps(comparison).encode()
    report["artifacts"]["process-comparison.json"] = digest(artifacts["process-comparison.json"])
    with pytest.raises(ValueError, match="latest native"):
        store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def test_missing_native_execution_cannot_be_substituted_with_a_comparison(tmp_path):
    store, rid, report, artifacts, _ = setup(tmp_path)
    # Different review with no native evidence.
    from skillguard.review.store import ReviewStore
    empty = ReviewStore(tmp_path / "other-reviews")
    other = empty.capture(tmp_path / "pending.json")
    with pytest.raises(ValueError, match="requires"):
        empty.record_candidate_process_comparison(other, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def test_later_execution_invalidates_comparison_and_model_advice(tmp_path):
    store, rid, report, artifacts, _ = setup(tmp_path)
    store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    store.record_advice(rid, json.dumps({"recommendation": "hold", "evidence_ids": ["E9"],
                                       "explanation": "Partial control comparison."}),
                        source="recorded-test")
    report["candidate_execution"]["mismatched_fields"] = ["tax", "total"]
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    decision = store.decide(rid)
    assert "Native process comparison refers to an older execution" in decision["reasons"]
    assert "Model advice refers to an older evidence revision" in decision["reasons"]
    assert store.evidence(rid)["E9"]["value"]["current_execution"] is False


def test_modified_control_cannot_be_presented_as_empty_python(tmp_path):
    store, rid, report, artifacts, _ = setup(tmp_path)
    image = json.loads(artifacts["candidate-image.json"])
    image["control_sha256"] = digest(b"print('not empty')\n")
    artifacts["candidate-image.json"] = json.dumps(image).encode()
    report["artifacts"]["candidate-image.json"] = digest(artifacts["candidate-image.json"])
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    with pytest.raises(ValueError, match="immutable empty"):
        store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def mutation_setup(tmp_path):
    rows = capture()
    rows[5].update({"evt.type": "unlinkat", "evt.rawres": 0,
                    "fs.path.name": "/sandbox/deleted", "evt.arg.flags": "0"})
    rows[6].update({"evt.type": "openat", "evt.rawres": 4,
                    "fs.path.name": "/sandbox/possible", "evt.arg.flags": "O_CREAT|O_RDWR"})
    return setup(tmp_path, rows)


def test_mutations_and_possible_creation_are_persisted_separately_without_approval(tmp_path):
    store, rid, report, artifacts, comparison = mutation_setup(tmp_path)
    store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    from skillguard.review.store import ReviewStore

    reopened = ReviewStore(store.root)
    value = reopened.evidence(rid)["E9"]["value"]
    assert value["after_file_mutations"] == comparison["after_file_mutations"]
    assert value["diff"]["added"]["files_written"] == [
        "/child-output.txt", "/output.json", "/sandbox/deleted"]
    assert value["path_mutation_capabilities_diff"]["added"]["files_written"] == [
        "/sandbox/possible"]
    assert reopened.decide(rid)["activation_permitted"] is False


def test_mutation_records_cannot_be_forged_by_updating_the_attachment_manifest(tmp_path):
    store, rid, report, artifacts, comparison = mutation_setup(tmp_path)
    comparison["after_file_mutations"] = []
    artifacts["process-comparison.json"] = json.dumps(comparison).encode()
    report["artifacts"]["process-comparison.json"] = digest(artifacts["process-comparison.json"])
    # Even if re-attached to the latest execution, native rows determine the facts.
    store.record_candidate_execution_probe(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    with pytest.raises(ValueError, match="native process evidence"):
        store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                                  artifacts=artifacts)


def test_mapping_permission_change_remains_visible_after_reopening_review(tmp_path):
    rows = capture()
    rows[5].update({"evt.type": "mprotect", "evt.dir": ">", "evt.rawres": None,
                    "evt.arg.addr": "2000", "evt.arg.length": "4096",
                    "evt.arg.prot": "PROT_READ|PROT_WRITE"})
    rows[6].update({"evt.type": "mprotect", "evt.rawres": 0})
    store, rid, report, artifacts, comparison = setup(tmp_path, rows)
    store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    from skillguard.review.store import ReviewStore

    reopened = ReviewStore(store.root)
    value = reopened.evidence(rid)["E9"]["value"]
    assert value["after_mapping_changes"] == comparison["after_mapping_changes"]
    assert value["after_mapping_changes"][0]["protection"] == "PROT_READ|PROT_WRITE"
    assert "sysdig:7" in value["after_unresolved_events"]
    assert reopened.decide(rid)["activation_permitted"] is False


def test_pre_lifecycle_review_evidence_remains_readable(tmp_path):
    store, rid, report, artifacts, _ = setup(tmp_path)
    store.record_candidate_process_comparison(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    historical = store.get(rid)["latest"]["candidate_process_comparison"].copy()
    for key in ("mapping_lifecycle_semantics_version", "before_mapping_changes",
                "after_mapping_changes"):
        historical.pop(key)
    store._append(rid, "candidate_process_comparison", historical)
    assert "after_mapping_changes" not in store.evidence(rid)["E9"]["value"]
    assert store.decide(rid)["activation_permitted"] is False
