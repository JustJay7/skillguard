"""Positive guide-before-input I/O witnesses inside the native agent execution window."""
import json

GUIDE = '/workspace/skills/receipt-organizer/SKILL.md'
INPUT = '/workspace/input/receipt.txt'


def observed(events: bytes, first: float, last: float, *, include_refresh: bool = False) -> dict:
    reads = {GUIDE: [], INPUT: []}
    for line in events.decode().splitlines():
        row = json.loads(line)
        if (row.get('fd.name') in reads and first <= row['evt.rawtime'] <= last
                and row.get('evt.dir') == '<' and (row.get('evt.rawres') or 0) > 0
                and row.get('evt.type') in {'read', 'pread', 'readv', 'preadv', 'preadv2'}):
            reads[row['fd.name']].append((row['evt.rawtime'], row['evt.num']))
    guide, source = [min(rows) if rows else None for rows in reads.values()]
    result = {'guide_before_receipt_observed': bool(guide and source and guide[0] < source[0]),
        'first_guide_read': 'sysdig:' + str(guide[1]) if guide else None,
        'first_receipt_read': 'sysdig:' + str(source[1]) if source else None,
        'scope': 'Positive reported read ordering during agent execution; discovery reads '
                 'are excluded. No claim about model comprehension.'}

    if include_refresh:
        later = [row for row in reads[GUIDE] if source and row[0] > source[0]]
        refresh = min(later) if later else None
        result.update(guide_after_receipt_observed=bool(refresh),
            guide_refresh_reference='sysdig:' + str(refresh[1]) if refresh else None)
    return result
