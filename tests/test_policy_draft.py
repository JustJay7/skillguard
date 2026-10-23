import pytest

from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.policy.draft import draft_policy


def test_receipt_contract_does_not_grant_private_file_or_canary_network() -> None:
    draft = draft_policy(
        BehavioralEnvelope(files_read=["/tmp/receipt"], files_written=["/tmp/output"]),
        runtime_read_only=["/usr", "/lib"],
    )
    policy = draft["policy"]
    assert "/tmp/private" not in policy["filesystem_policy"]["read_only"]
    assert "/tmp" not in policy["filesystem_policy"]["read_write"]
    assert "network_policies" not in policy
    assert policy["filesystem_policy"]["include_workdir"] is False
    assert policy["landlock"]["compatibility"] == "hard_requirement"
    assert draft["applied"] is False


@pytest.mark.parametrize("path", ["relative", "/", "/tmp/*", "/tmp/../private", "/tmp/", "//tmp"])
def test_unsafe_or_overbroad_filesystem_grants_are_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        draft_policy(BehavioralEnvelope(files_read=[path]), runtime_read_only=["/usr"])


def test_unverified_network_or_process_permissions_are_not_silently_omitted() -> None:
    with pytest.raises(ValueError, match="network"):
        draft_policy(BehavioralEnvelope(network_hosts=["127.0.0.1:8765"]), runtime_read_only=[])
    with pytest.raises(ValueError, match="process"):
        draft_policy(BehavioralEnvelope(processes=["/bin/sh"]), runtime_read_only=[])
