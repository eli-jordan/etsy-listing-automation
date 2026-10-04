"""Explicit versioned native Windows inference installation (ADR-0053)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ENGINE_VERSION = '1.0.0'


@dataclass(frozen=True)
class Capability:
    available: bool
    problem: str | None
    engine_version: str | None = None
    required_engine: str = ENGINE_VERSION


class Runtime:
    def __init__(self, *, home: Path | None = None) -> None:
        self.root = (home or Path.home()) / '.etsy-listings' / 'marigold'

    def inspect(self) -> Capability:
        return Capability(False, 'Run etsy-listings marigold setup to install the native worker.')
