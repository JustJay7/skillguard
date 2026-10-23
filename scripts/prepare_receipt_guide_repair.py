"""Stage a guide-only repair with native Hermes; validate without model inference."""
from __future__ import annotations

import argparse
import base64
import json
import uuid
from pathlib import Path

from scripts.learned_candidate_image import candidate_payload
from skillguard.core import CoreWorkspace
from skillguard.review.snapshot import digest


def prepare(root: Path, source: Path | None = None) -> Path:
    parent_path = root / 'results/integration/local-parser-8fc64684/preparation.json'
    parent = candidate_payload(root, parent_path)
    source = (source or root / 'skills/repaired-v8/receipt-organizer').resolve()
    if not source.is_relative_to(root / 'skills'):
        raise ValueError('Repair source must be local to project skills')
    guide = (source / 'SKILL.md').read_text()
    parser = base64.b64decode(parent['files']['scripts/parse_receipt.py']).decode()
    if (source / 'scripts/parse_receipt.py').read_text() != parser:
        raise ValueError('Guide-only repair cannot change the source parser')
    folder = root / 'results/integration' / ('receipt-guide-repair-' + uuid.uuid4().hex[:8])
    w = CoreWorkspace(root, folder)
    staged = w.native(w.profile, 'stage', {'action': '', 'name': '', 'operations': [
        {'action': 'create', 'name': 'receipt-organizer', 'content': guide},
        {'action': 'write_file', 'name': 'receipt-organizer',
         'file_path': 'scripts/parse_receipt.py', 'file_content': parser}]})
    if staged.get('staged') is not True:
        raise ValueError('Native repair staging failed')
    rid, = w.detect()
    test = w.test(rid)
    if not test['passed']:
        raise ValueError('Native repair preparation failed; preserve diagnostics')
    review = w.store.get(rid)
    data = {'kind': 'receipt-guide-repair-v1', 'parent_preparation': str(parent_path),
        'parent_candidate_sha256': parent['candidate_sha256'], 'store': str(w.store.root),
        'review_id': rid, 'candidate_sha256': review['candidate_sha256'],
        'parser_sha256': parent['parser_sha256'], 'guide_sha256': digest(guide.encode()),
        'fresh_holdout_seen_during_repair': False, 'model_calls_during_repair': 0,
        'repair_input': 'Original guide, known development failure and general trust boundary',
        'source': str(source),
        'activation_permitted': False}
    path = folder / 'preparation.json'
    path.write_text(json.dumps(data, indent=2) + '\n')
    from skillguard.evaluation.receipt_repair import payload

    payload(root, path)
    (root / 'results/receipt-guide-repair-latest.json').write_text(str(path) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    print(prepare(Path(__file__).resolve().parents[1], args.source))
