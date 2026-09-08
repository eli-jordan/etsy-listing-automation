"""Actionable config-loading errors.

Every error here names the offending file and field, per the PRD's validation
section: failures must be actionable, never a bare stack trace.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from etsy_listings.errors import UserFacingError


class ConfigLoadError(UserFacingError, ValueError):
    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        super().__init__(f"{path}: {detail}")


def format_validation_error(path: Path, exc: ValidationError) -> ConfigLoadError:
    lines = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        lines.append(f"  {loc}: {error['msg']}")
    return ConfigLoadError(path, "invalid configuration:\n" + "\n".join(lines))
