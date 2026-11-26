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

from etsy_listings.core.config.listing import Listing, canonical_document
from etsy_listings.core.errors import ConflictError, MissingError
from etsy_listings.core.workspace import locks
from etsy_listings.core.workspace.atomic import read_bytes_retrying, write_yaml_atomic
from etsy_listings.core.workspace.workspace import Workspace

Document = dict[str, Any]
"""``listing.yaml`` as written: the raw mapping, not a validated
:class:`Listing`. An edit must keep the keys it does not understand."""


class ListingMissingError(MissingError):
    """There is no ``listing.yaml`` by this name. Either there never was, or
    a rename or delete holding the listing's lock moved it first."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no listing {name!r}")
        self.name = name


class ListingNameTakenError(ConflictError, ValueError):
    """A create or rename named a listing directory that already exists,
    with or without a ``listing.yaml`` in it."""

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
        """``name``'s document as written. Raises :class:`ListingMissingError`
        when there is none. Unlike :meth:`Workspace.load_listing`, this does
        not validate it."""
        path = self._workspace.listing_file(name)
        try:
            text = read_bytes_retrying(path).decode("utf-8")
        except FileNotFoundError:
            raise ListingMissingError(name) from None
        raw = yaml.safe_load(text)
        return raw if isinstance(raw, dict) else {}

    def edit(self, name: str, change: Callable[[Document], Document | None]) -> Document | None:
        """Pass ``name``'s document to ``change`` and write what it returns,
        holding the lock throughout. Returns the written document.

        ``change`` returns ``None`` to write nothing, and that is returned.
        If it raises, nothing is written and the exception propagates.
        Raises :class:`ListingMissingError` when there is no document, whether
        before or after waiting for the lock.

        The document is not validated here. The editor's patch validates what
        it merged, but the tool's own small edits (a brief, a lifecycle mark)
        must still apply to a document a seller has broken by hand.
        """
        with self.lock(name):
            current = self.read(name)
            # Callbacks may mutate nested values. Compare against the saved
            # document, not the same object the callback was allowed to edit.
            changed = change(copy.deepcopy(current))
            # Unchanged is a semantic no-op even when `design:` is in its old
            # form: canonicalising alone is not a reason to touch the file.
            if changed is not None and changed != current:
                changed = canonical_document(changed)
                self._write(name, changed)
            return changed

    def create(self, name: str, document: Mapping[str, Any]) -> Path:
        """Write ``document`` as the new listing ``name`` and return its path.

        Checks, in order and holding the lock:

        * ``InvalidNameError``: ``name`` is not a single path segment
          (ADR-0013).
        * :class:`ListingNameTakenError`: the name is not :meth:`is_free`.
        * ``pydantic.ValidationError``: ``document`` does not validate
          structurally. An incomplete document validates and is written
          (ADR-0043).
        """
        with self.lock(name):
            if not self.is_free(name):
                raise ListingNameTakenError(name)
            return self.write(name, document)

    def write(self, name: str, document: Mapping[str, Any]) -> Path:
        """Write ``document`` as ``name`` whether or not one is there, and
        return its path. Raises ``pydantic.ValidationError``, writing nothing,
        when ``document`` does not validate structurally.

        Only for a writer that has already decided the name is its own:
        :meth:`create`, and a batch re-entering a row it claimed.
        """
        with self.lock(name):
            Listing.model_validate(
                dict(document), context={"currency": self._workspace.defaults.etsy.currency}
            )
            return self._write(name, document)

    def _write(self, name: str, document: Mapping[str, Any]) -> Path:
        path = self._workspace.listing_file(name)
        # Every write normalises `design:` to its map form (ADR-0053): a bare
        # string or `null` written by hand converges on the one written form
        # the next time anything saves.
        canonical = canonical_document(document)
        write_yaml_atomic(
            path,
            canonical,
            new=lambda: yaml.safe_dump(canonical, sort_keys=False, allow_unicode=True),
        )
        return path
