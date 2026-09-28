"""Windows' refusal to open a file mid-replace, injected on any platform.

Windows refuses to open a file while another thread is ``os.replace``-ing
onto it, with a bare ``PermissionError`` (WinError 5). The CI runner meets
that by chance; these tests meet it on purpose.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def refuse_reads(monkeypatch: pytest.MonkeyPatch, times: int) -> list[float]:
    """Refuse the next ``times`` opens of a file for reading -- ``Path.open``,
    under both ``read_bytes`` and ``read_text`` -- and record the atomic
    helpers' back-off sleeps instead of sleeping them. Returns the sleeps."""
    real = Path.open
    refusals = iter([PermissionError(13, "Access is denied")] * times)

    def busy(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if "r" in mode and "+" not in mode:
            refusal = next(refusals, None)
            if refusal is not None:
                raise refusal
        return real(self, mode, *args, **kwargs)

    sleeps: list[float] = []
    monkeypatch.setattr(Path, "open", busy)
    monkeypatch.setattr("etsy_listings.workspace.atomic.time.sleep", sleeps.append)
    return sleeps
