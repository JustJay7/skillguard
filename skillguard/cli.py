from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from skillguard.envelope.diff import diff_envelopes
from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.evaluation.skillevaluator import SkillEvaluatorRunner
from skillguard.intercept.reconstruct import HermesReconstructor
from skillguard.intercept.reject import reject_pending
from skillguard.review.store import ReviewStore


def _load_envelope(path: Path) -> BehavioralEnvelope:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return BehavioralEnvelope.from_dict(payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillguard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    diff_parser = subparsers.add_parser("diff", help="compare two behavioral envelopes")
    diff_parser.add_argument("before", type=Path)
    diff_parser.add_argument("after", type=Path)
    for command in ("capture", "inspect", "scan", "decide", "capture-probe", "reject"):
        review_parser = subparsers.add_parser(command, help=f"{command} a persistent skill review")
        review_parser.add_argument("target", type=Path if command == "capture" else str)
        review_parser.add_argument("--store", type=Path, default=Path("results/reviews"))
        if command == "scan":
            review_parser.add_argument("--evaluator", default="skillevaluator")
        if command == "capture":
            review_parser.add_argument("--baseline", type=Path)
            review_parser.add_argument("--hermes-source", type=Path)
        if command == 'reject':
            review_parser.add_argument('--hermes-source', type=Path, required=True)
            review_parser.add_argument('--hermes-profile', type=Path, required=True)
        if command == "capture-probe":
            review_parser.add_argument(
                "--report", type=Path, required=True,
                help="Fixed native infrastructure report, not candidate replay",
            )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "diff":
        before = _load_envelope(args.before)
        after = _load_envelope(args.after)
        print(json.dumps(diff_envelopes(before, after).to_dict(), indent=2, sort_keys=True))
        return 0
    store = ReviewStore(args.store)
    if args.command == "capture":
        result = {
            "review_id": store.capture(
                args.target,
                baseline=args.baseline,
                native_apply=HermesReconstructor(args.hermes_source)
                if args.hermes_source
                else None,
            )
        }
    elif args.command == "inspect":
        result = store.get(args.target)
    elif args.command == "scan":
        result = store.run_static(args.target, SkillEvaluatorRunner(binary=args.evaluator))
    elif args.command == "decide":
        result = store.decide(args.target)
    elif args.command == 'reject':
        native = HermesReconstructor(args.hermes_source)
        sys.path.insert(0, str(native.source))
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        token = set_hermes_home_override(args.hermes_profile.resolve())
        try:
            result = reject_pending(store, args.target,
                                    hermes_home=args.hermes_profile.resolve())
        finally:
            reset_hermes_home_override(token)
    elif args.command == "capture-probe":
        raw = args.report.read_bytes()
        manifest = json.loads(raw).get("artifacts", {})
        artifacts = {}
        for name in manifest:
            if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
                raise ValueError("native report artifact must be a local filename")
            path = args.report.parent / name
            if path.is_symlink():
                raise ValueError("native report artifact must not be a symlink")
            artifacts[name] = path.read_bytes()
        result = store.record_capture_probe(args.target, report=raw, artifacts=artifacts)
    else:
        raise AssertionError(f"unhandled command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
