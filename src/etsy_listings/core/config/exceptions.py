"""Loads ``exceptions.yaml`` -- the sparse colour-slug override file, ADR-0004."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from etsy_listings.core.config.errors import format_validation_error, parse_yaml
from etsy_listings.core.config.slug import ColourExceptions


def load_exceptions(path: Path) -> ColourExceptions:
    """Load ``exceptions.yaml`` if present; an absent file means "no exceptions"."""
    if not path.is_file():
        return ColourExceptions(root={})
    raw = parse_yaml(path, path.read_text(encoding="utf-8")) or {}
    try:
        return ColourExceptions.model_validate(raw)
    except ValidationError as exc:
        raise format_validation_error(path, exc) from exc
