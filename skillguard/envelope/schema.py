from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

_FIELDS = ("files_read", "files_written", "network_hosts", "processes", "tools")


def _freeze(values: Iterable[str] | None) -> frozenset[str]:
    if values is None:
        return frozenset()
    return frozenset(str(value) for value in values)


@dataclass(frozen=True, slots=True)
class BehavioralEnvelope:
    """Deterministic summary of behavior observed during a skill execution."""

    files_read: frozenset[str] = field(default_factory=frozenset)
    files_written: frozenset[str] = field(default_factory=frozenset)
    network_hosts: frozenset[str] = field(default_factory=frozenset)
    processes: frozenset[str] = field(default_factory=frozenset)
    tools: frozenset[str] = field(default_factory=frozenset)

    def __init__(
        self,
        *,
        files_read: Iterable[str] | None = None,
        files_written: Iterable[str] | None = None,
        network_hosts: Iterable[str] | None = None,
        processes: Iterable[str] | None = None,
        tools: Iterable[str] | None = None,
    ) -> None:
        object.__setattr__(self, "files_read", _freeze(files_read))
        object.__setattr__(self, "files_written", _freeze(files_written))
        object.__setattr__(self, "network_hosts", _freeze(network_hosts))
        object.__setattr__(self, "processes", _freeze(processes))
        object.__setattr__(self, "tools", _freeze(tools))

    def to_dict(self) -> dict[str, list[str]]:
        return {name: sorted(getattr(self, name)) for name in _FIELDS}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BehavioralEnvelope:
        return cls(**{name: payload.get(name, []) for name in _FIELDS})
