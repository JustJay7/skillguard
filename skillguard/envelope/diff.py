from __future__ import annotations

from dataclasses import dataclass

from .schema import BehavioralEnvelope


@dataclass(frozen=True, slots=True)
class BehavioralDiff:
    added: BehavioralEnvelope
    removed: BehavioralEnvelope

    @property
    def is_empty(self) -> bool:
        return self.added == BehavioralEnvelope() and self.removed == BehavioralEnvelope()

    def to_dict(self) -> dict[str, dict[str, list[str]]]:
        return {"added": self.added.to_dict(), "removed": self.removed.to_dict()}


def _subtract(left: BehavioralEnvelope, right: BehavioralEnvelope) -> BehavioralEnvelope:
    return BehavioralEnvelope(
        files_read=left.files_read - right.files_read,
        files_written=left.files_written - right.files_written,
        network_hosts=left.network_hosts - right.network_hosts,
        processes=left.processes - right.processes,
        tools=left.tools - right.tools,
    )


def diff_envelopes(before: BehavioralEnvelope, after: BehavioralEnvelope) -> BehavioralDiff:
    """Return deterministic capability additions/removals from before -> after."""

    return BehavioralDiff(added=_subtract(after, before), removed=_subtract(before, after))
