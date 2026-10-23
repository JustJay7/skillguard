import json

import pytest

from skillguard.traces.sysdig import parse_sysdig
from tests.test_process_scope import CONTAINER, row


def event(kind='write', **updates):
    value = row(1, 30, 300, kind)
    value.update({'fd.type': 'ipv4', 'fd.num': 5, 'fd.name': 'native socket',
                  'fd.l4proto': 'tcp', 'fd.is_server': False,
                  'fd.rip': '127.0.0.1', 'fd.rport': 12345})
    value.update(updates)
    return value


def parse(*values):
    return parse_sysdig('\n'.join(json.dumps(v) for v in values), container_id=CONTAINER)


def test_socket_write_keeps_completed_byte_count_and_native_remote_peer():
    evidence = parse(event())
    assert evidence.envelope.files_written == set()
    assert evidence.envelope.network_hosts == {'127.0.0.1:12345'}
    assert evidence.socket_io[0]['bytes_transferred'] == 10
    assert evidence.socket_io[0]['direction'] == 'outgoing'
    assert evidence.socket_io[0]['peer_endpoint'] == '127.0.0.1:12345'
    assert evidence.socket_io[0]['process_identity'] == [30, 300]
    assert evidence.event_refs['network_writes:127.0.0.1:12345'] == ['sysdig:1']
    assert evidence.unresolved_events  # no descriptor lifetime/capture completeness proof
    assert evidence.complete is False


def test_inbound_socket_reports_native_remote_field_without_outbound_permission():
    evidence = parse(event('read', **{'fd.is_server': True, 'fd.rip': '127.0.0.2'}))
    assert evidence.socket_io[0]['peer_endpoint'] == '127.0.0.2:12345'
    assert evidence.envelope.network_hosts == set()
    assert evidence.event_refs['network_reads:127.0.0.2:12345'] == ['sysdig:1']


@pytest.mark.parametrize('kind', ['sendmmsg', 'recvmmsg'])
def test_batch_message_count_never_becomes_a_byte_count(kind):
    evidence = parse(event(kind))
    assert evidence.socket_io == []
    assert 'batch message' in evidence.unresolved_events['sysdig:1']


@pytest.mark.parametrize('kind,descriptor', [('write', 'pipe'), ('readv', 'pipe'),
                                          ('sendmsg', 'unix'), ('recvmsg', 'unix')])
def test_successful_ipc_is_visible_but_does_not_invent_files_or_peers(kind, descriptor):
    evidence = parse(event(kind, **{'fd.type': descriptor, 'fd.rip': None, 'fd.rport': None}))
    assert evidence.socket_io[0]['bytes_transferred'] == 10
    assert evidence.socket_io[0]['peer_endpoint'] is None
    assert evidence.envelope.network_hosts == set()
    assert evidence.envelope.files_read == evidence.envelope.files_written == set()
    assert 'IPC peer' in evidence.unresolved_events['sysdig:1']


@pytest.mark.parametrize('field,value', [('fd.rip', None), ('fd.rip', 'not-an-ip'),
    ('fd.rport', True), ('fd.rport', 65536), ('fd.num', None), ('proc.pid.ts', None),
    ('fd.l4proto', 'raw'), ('fd.rip', 2130706433), ('fd.rip', '::1')])
def test_missing_or_unsupported_peer_metadata_never_adds_a_network_host(field, value):
    evidence = parse(event(**{field: value}))
    assert evidence.envelope.network_hosts == set()
    assert evidence.unresolved_events


@pytest.mark.parametrize('result', [-13, 0])
def test_failed_or_eof_stream_io_does_not_claim_completed_bytes(result):
    evidence = parse(event(**{'evt.rawres': result}))
    assert evidence.socket_io == []
    assert evidence.envelope.network_hosts == set()


def test_unconnected_udp_send_without_input_tuple_cannot_use_a_stale_remote_peer():
    evidence = parse(event('sendto', **{'fd.l4proto': 'udp'}))
    assert evidence.envelope.network_hosts == set()
    assert 'datagram destination' in evidence.unresolved_events['sysdig:1']


def test_successful_unknown_descriptor_and_unix_connect_do_not_disappear():
    assert parse(event(**{'fd.type': None})).unresolved_events
    evidence = parse(event('connect', **{'fd.type': 'unix', 'evt.rawres': 0}))
    assert 'connect' in evidence.unresolved_events['sysdig:1']


def test_socket_identity_loss_cannot_use_truncated_container_binding():
    with pytest.raises(ValueError, match='exact native container identity'):
        parse(event('sendmsg', **{'container.full_id': None}))


@pytest.mark.parametrize('kind', ['recvfrom', 'recvmsg', 'sendmsg', 'sendto'])
def test_zero_byte_messages_cannot_hide_ancillary_or_datagram_activity(kind):
    evidence = parse(event(kind, **{'evt.rawres': 0}))
    assert evidence.socket_io == []
    assert 'zero-byte message' in evidence.unresolved_events['sysdig:1']


def test_successful_socket_call_mistyped_as_file_cannot_disappear():
    evidence = parse(event('sendmsg', **{'fd.type': 'file'}))
    assert evidence.unresolved_events
    assert evidence.envelope.files_written == set()


def test_ipv6_socket_endpoint_is_bracketed_without_domain_invention():
    evidence = parse(event(**{'fd.type': 'ipv6', 'fd.rip': '::1'}))
    assert evidence.envelope.network_hosts == {'[::1]:12345'}
