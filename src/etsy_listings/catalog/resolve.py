"""Name -> id resolution. Config refers to blueprints and print providers by name
(PRD 23); this is the only place that turns a name into a Printify integer id."""

from __future__ import annotations

from etsy_listings.catalog.models import Blueprint, PrintProvider


class CatalogResolutionError(ValueError):
    def __init__(self, kind: str, name: str, valid_names: list[str]) -> None:
        self.kind = kind
        self.name = name
        self.valid_names = valid_names
        options = ", ".join(sorted(valid_names)) or "(none available)"
        super().__init__(f"no {kind} named {name!r}. Valid names: {options}")


def resolve_blueprint(name: str, blueprints: list[Blueprint]) -> Blueprint:
    for blueprint in blueprints:
        if blueprint.title == name:
            return blueprint
    raise CatalogResolutionError("blueprint", name, [b.title for b in blueprints])


def resolve_print_provider(name: str, providers: list[PrintProvider]) -> PrintProvider:
    for provider in providers:
        if provider.title == name:
            return provider
    raise CatalogResolutionError("print provider", name, [p.title for p in providers])
