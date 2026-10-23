"""Adapt supplied native socket/IPC metadata; no capture or enforcement service."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from skillguard.traces.native_calls import native_thread_identity

READ_KINDS = frozenset({'read', 'pread', 'readv', 'preadv', 'preadv2'})
WRITE_KINDS = frozenset({'write', 'pwrite', 'writev', 'pwritev', 'pwritev2'})
SEND_KINDS = frozenset({'send', 'sendto', 'sendmsg', 'sendmmsg'})
RECEIVE_KINDS = frozenset({'recv', 'recvfrom', 'recvmsg', 'recvmmsg'})
SOCKET_KINDS = SEND_KINDS | RECEIVE_KINDS


def native_remote_endpoint(row: dict) -> str | None:
    # Server/client fields are not interchangeable with the owning process's peer.
    if row.get('fd.l4proto') not in {'tcp', 'udp'}:
        return None
    address, port = row.get('fd.rip'), row.get('fd.rport')
    if (not isinstance(address, str) or '%' in address
            or type(port) is not int or not 1 <= port <= 65535):
        return None
    try:
        address = ipaddress.ip_address(address)
    except (ValueError, TypeError):
        return None
    family = {'ipv4': 4, 'ipv6': 6}.get(row.get('fd.type'))
    if address.version != family or address.is_unspecified:
        return None
    return f'[{address}]:{port}' if address.version == 6 else f'{address}:{port}'


@dataclass
class NativeSocketIO:
    operations: list[dict] = field(default_factory=list)
    gaps: dict[str, str] = field(default_factory=dict)

    def gap(self, row: dict, detail: str) -> None:
        self.gaps[f"sysdig:{row['evt.num']}"] = (
            row['evt.type'] + ' access not fully represented; ' + detail)

    def consume(self, row: dict) -> dict | None:
        kind, descriptor = row['evt.type'], row.get('fd.type')
        if row['evt.dir'] != '<':
            return None
        if kind == 'connect':
            if descriptor not in {'ipv4', 'ipv6'}:
                self.gap(row, 'connect peer/destination unresolved')
            return None
        if (kind not in READ_KINDS | WRITE_KINDS | SOCKET_KINDS
                or descriptor == 'file' and kind in READ_KINDS | WRITE_KINDS):
            return None
        result = row.get('evt.rawres')
        if type(result) is not int:
            raise ValueError('Missing or invalid native socket/IPC return value')
        if kind in {'sendmmsg', 'recvmmsg'}:
            if result >= 0:
                self.gap(row, 'batch message outcomes/peers and byte counts unresolved')
            return None
        if result <= 0:
            if kind in SEND_KINDS or result == 0 and (
                    kind in RECEIVE_KINDS or row.get('fd.l4proto') == 'udp'):
                self.gap(row, 'socket attempt/zero-byte message or ancillary data unresolved; '
                         'no positive byte count')
            return None
        identity, fd = native_thread_identity(row), row.get('fd.num')
        if identity is None or type(fd) is not int or fd < 0:
            self.gap(row, 'process/thread or descriptor identity unresolved')
            return None
        outgoing = kind in WRITE_KINDS | SEND_KINDS
        endpoint = None
        if descriptor in {'ipv4', 'ipv6'}:
            # Per-datagram destinations can differ from a socket's previous peer.
            if row.get('fd.l4proto') == 'udp':
                self.gap(row, 'datagram destination/source tuple not paired')
            else:
                endpoint = native_remote_endpoint(row)
                self.gap(row, 'descriptor sharing/lifetime and delivery not reconstructed'
                         if endpoint else 'native remote peer or protocol unresolved')
        elif descriptor in {'unix', 'pipe', 'netlink'}:
            self.gap(row, 'IPC peer/descriptor lifetime and ancillary data unresolved')
        else:
            self.gap(row, 'completed non-file descriptor I/O not represented')
            return None
        operation = {'kind': kind, 'descriptor_type': descriptor, 'fd': fd,
            'process_identity': list(identity[:2]), 'thread_id': identity[2],
            'direction': 'outgoing' if outgoing else 'incoming',
            'bytes_transferred': result, 'peer_endpoint': endpoint,
            'protocol': row.get('fd.l4proto'), 'native_descriptor': row.get('fd.name'),
            'exit_ref': f"sysdig:{row['evt.num']}", 'complete': False,
            'payload_observed': False, 'delivery_proven': False}
        self.operations.append(operation)
        return operation
