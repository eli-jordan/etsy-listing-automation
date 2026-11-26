"""``listings/<name>/listing.yaml``: the one way to read, edit and write it.

The listing locks do not cover a second process, such as the CLI running
beside the UI server.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from etsy_listings.core.config.listing import Listing
from etsy_listings.core.errors import ConflictError, MissingError
from etsy_listings.core.workspace import locks
from etsy_listings.core.workspace.atomic import read_bytes_retrying, write_yaml_atomic
from etsy_listings.core.workspace.workspace import Workspace

Document = dict[str, Any]
"""``listing.yaml`` as written: the raw mapping, not a validated
:class:`Listing`. An edit must keep the keys it does not understand."""


class ListingMissingError(MissingError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no listing {name!r}")
        self.name = name


class ListingNameTakenError(ConflictError, ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"a listing already exists named {name!r}")
        self.name = name


class ListingDocuments:
    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @contextmanager
    def lock(self, name: str, *more: str) -> Iterator[None]:
        with locks.hold(self._workspace, "listing", name, *more):
            yield

    def exists(self, name: str) -> bool:
        return self._workspace.listing_file(name).is_file()

    def is_free(self, name: str) -> bool:
        return not self._workspace.listing_dir(name).exists()

    def read(self, name: str) -> Document:
        path = self._workspace.listing_file(name)
        try:
            text = read_bytes_retrying(path).decode("utf-8")
        except FileNotFoundError:
            raise ListingMissingError(name) from None
        raw = yaml.safe_load(text)
        return raw if isinstance(raw, dict) else {}

    def edit(self, name: str, change: Callable[[Document], Document | None]) -> Document | None:
        with self.lock(name):
            current = self.read(name)
            # A copy, so a callback that mutates in place still compares unequal.
            changed = change(copy.deepcopy(current))
            if changed is not None and changed != current:
                self._write(name, changed)
            return changed

    def create(self, name: str, document: Mapping[str, Any]) -> Path:
        with self.lock(name):
            if not self.is_free(name):
                raise ListingNameTakenError(name)
            return self.write(name, document)

    def write(self, name: str, document: Mapping[str, Any]) -> Path:
        """Overwrites: only for a writer that already owns ``name``."""
        with self.lock(name):
            Listing.model_validate(
                dict(document), context={"currency": self._workspace.defaults.etsy.currency}
            )
            return self._write(name, document)

    def _write(self, name: str, document: Mapping[str, Any]) -> Path:
        path = self._workspace.listing_file(name)
        write_yaml_atomic(
            path,
            document,
            new=lambda: yaml.safe_dump(dict(document), sort_keys=False, allow_unicode=True),
        )
        return path
