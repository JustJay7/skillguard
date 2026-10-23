"""Validate a new guide-only derivative without weakening the old candidate guard."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from skillguard.core_agent import parser_checks_valid
from skillguard.review.snapshot import digest, snapshot_digest
from skillguard.review.store import ReviewStore


def payload(root: Path, preparation: Path) -> dict:
    from scripts.learned_candidate_image import candidate_payload

    preparation = preparation.resolve()
    if not preparation.is_relative_to((root / 'results/integration').resolve()):
        raise ValueError('Repair preparation must remain local')
    data = json.loads(preparation.read_text())
    parent = candidate_payload(root, Path(data['parent_preparation']))
    store = Path(data['store']).resolve()
    if not store.is_relative_to(preparation.parent):
        raise ValueError('Repair store escaped its preparation')
    review = ReviewStore(store).get(data['review_id'])
    snapshot = Path(review['snapshot'])
    paths = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*') if p.is_file()}
    parser = snapshot / 'scripts/parse_receipt.py'
    if (data.get('kind') != 'receipt-guide-repair-v1' or not parser_checks_valid(review)
            or paths != {'SKILL.md', 'scripts/parse_receipt.py'}
            or data.get('parent_candidate_sha256') != parent['candidate_sha256']
            or data.get('candidate_sha256') != snapshot_digest(snapshot)
            or data['candidate_sha256'] != review['candidate_sha256']
            or data.get('parser_sha256') != parent['parser_sha256']
            or digest(parser.read_bytes()) != parent['parser_sha256']
            or digest((snapshot / 'SKILL.md').read_bytes()) != data.get('guide_sha256')
            or data.get('fresh_holdout_seen_during_repair') is not False):
        raise ValueError('Guide repair identity or native preparation differs')
    return {**data, 'files': {name: base64.b64encode((snapshot / name).read_bytes()).decode()
                            for name in paths}, 'snapshot': str(snapshot)}
