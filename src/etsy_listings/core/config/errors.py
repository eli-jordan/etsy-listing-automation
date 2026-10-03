"""Actionable config-loading errors.

Every error here names the offending file and field, under the validation rules: failures must be
actionable, never a bare stack trace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from etsy_listings.core.errors import UserFacingError


class ConfigLoadError(UserFacingError, ValueError):
    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        super().__init__(f"{path}: {detail}")


def parse_yaml(path: Path, text: str) -> Any:
    """``text`` (read from ``path``) parsed as YAML. A file YAML cannot parse
    is a :class:`ConfigLoadError` naming it, like one that fails validation:
    a hand edit makes either, and callers that skip an unloadable file must
    not see a bare parser error instead."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(path, f"not valid YAML: {exc}") from exc


def format_validation_error(path: Path, exc: ValidationError) -> ConfigLoadError:
    lines = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        lines.append(f"  {loc}: {error['msg']}")
    return ConfigLoadError(path, "invalid configuration:\n" + "\n".join(lines))
