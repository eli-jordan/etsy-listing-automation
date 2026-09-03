"""Loads ``exceptions.yaml`` -- the sparse colour-slug override file, PRD 7a."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from etsy_listings.config.errors import format_validation_error
from etsy_listings.config.slug import ColourExceptions


def load_exceptions(path: Path) -> ColourExceptions:
    """Load ``exceptions.yaml`` if present; an absent file means "no exceptions"."""
    if not path.is_file():
        return ColourExceptions(root={})
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return ColourExceptions.model_validate(raw)
    except ValidationError as exc:
        raise format_validation_error(path, exc) from exc
