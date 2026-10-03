"""``listings/<name>/listing.yaml``: the one way to read, edit and write it.

A listing document has several writers. The editor saves each field as the
seller moves between them, an AI run writes a brief in the background, a
delete marks it ``lifecycle: deleted``, an apply consumes ``lifecycle:
renew``, and a batch or the ``new`` wizard creates it. Each of those is a
read, a change and a write. If two interleave, the first write is lost
without a trace. Every writer therefore comes here. This module holds the
listing's lock around the whole sequence and re-checks the document once the
lock is held, because a rename or delete that held it first may have moved
it. It reads through the retrying reader and replaces the file atomically,
so a reader sees either the old document or the new one.

The lock is also the lock for everything else keyed by the listing's name:
its proposal record (``ai/proposals.py``), its market snapshot write and its
rename or removal (``listing_artifacts.py``). There is one lock per listing,
so there is no order between two kinds of lock to get wrong. The locks are
reentrant, so an operation that holds a listing's lock can call another that
takes it. They are process-wide and keyed by the resolved workspace root, so
every :class:`ListingDocuments` over one workspace shares them and one is
cheap to make. They do not cover a second process, such as the CLI running
beside the UI server, which nothing in the tool has ever guarded.

Two questions about a name have two answers, and each is answered only here.
:meth:`ListingDocuments.exists` asks whether there is a document to read or
edit. :meth:`ListingDocuments.is_free` asks whether a new listing may take the
name. A directory left behind with a lockfile and no document is not a
listing, but its name is not free either, because a new listing there would
inherit another listing's remote ids.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

import yaml

from etsy_listings.core.config.listing import Listing, canonical_document
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.atomic import read_bytes_retrying, write_bytes_atomic
from etsy_listings.core.workspace.workspace import Workspace

Document = dict[str, Any]
"""``listing.yaml`` as written: the raw mapping, not a validated
:class:`Listing`. An edit must keep the keys it does not understand."""


class ListingMissing(UserFacingError, LookupError):
    """There is no ``listing.yaml`` by this name. Either there never was, or
    a rename or delete holding the listing's lock moved it first."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no listing {name!r}")
        self.name = name


class ListingNameTaken(UserFacingError, ValueError):
    """A create or rename named a listing directory that already exists,
    with or without a ``listing.yaml`` in it."""

    def __init__(self, name: str) -> None:
        super().__init__(f"a listing already exists named {name!r}")
        self.name = name


_GUARD = threading.Lock()
_LOCKS: dict[tuple[str, str], threading.RLock] = {}


class ListingDocuments:
    """The listing documents of one workspace, and their locks."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @contextmanager
    def lock(self, name: str, *more: str) -> Iterator[None]:
        """Hold the lock for ``name``, and for each of ``more``, during the
        ``with`` block.

        Several names, such as a rename's old and new, are taken in one sorted
        order. Two callers naming the same pair therefore cannot each hold one
        and wait for the other. Names are compared case-insensitively, as
        Windows compares the directory names they become. A name that is not
        a single path segment raises ``InvalidNameError`` before any lock is
        taken.
        """
        for each in (name, *more):
            self._workspace.listing_dir(each)
        root = str(self._workspace.root.resolve())
        with ExitStack() as stack:
            for key in sorted({key.casefold() for key in (name, *more)}):
                with _GUARD:
                    lock = _LOCKS.setdefault((root, key), threading.RLock())
                stack.enter_context(lock)
            yield

    def exists(self, name: str) -> bool:
        """Is there a ``listing.yaml`` named ``name`` to read or edit?"""
        return self._workspace.listing_file(name).is_file()

    def is_free(self, name: str) -> bool:
        """May a new listing take ``name``? Only if no directory holds it."""
        return not self._workspace.listing_dir(name).exists()

    def read(self, name: str) -> Document:
        """``name``'s document as written. Raises :class:`ListingMissing`
        when there is none. Unlike :meth:`Workspace.load_listing`, this does
        not validate it."""
        path = self._workspace.listing_file(name)
        try:
            text = read_bytes_retrying(path).decode("utf-8")
        except FileNotFoundError:
            raise ListingMissing(name) from None
        raw = yaml.safe_load(text)
        return raw if isinstance(raw, dict) else {}

    def edit(self, name: str, change: Callable[[Document], Document | None]) -> Document | None:
        """Pass ``name``'s document to ``change`` and write what it returns,
        holding the lock throughout. Returns the written document.

        ``change`` returns ``None`` to write nothing, and that is returned.
        If it raises, nothing is written and the exception propagates.
        Raises :class:`ListingMissing` when there is no document, whether
        before or after waiting for the lock.

        The document is not validated here. The editor's patch validates what
        it merged, but the tool's own small edits (a brief, a lifecycle mark)
        must still apply to a document a seller has broken by hand.
        """
        with self.lock(name):
            changed = change(self.read(name))
            if changed is not None:
                self._write(name, changed)
            return changed

    def create(self, name: str, document: Mapping[str, Any]) -> Path:
        """Write ``document`` as the new listing ``name`` and return its path.

        Checks, in order and holding the lock:

        * ``InvalidNameError``: ``name`` is not a single path segment
          (ADR-0013).
        * :class:`ListingNameTaken`: the name is not :meth:`is_free`.
        * ``pydantic.ValidationError``: ``document`` does not validate
          structurally. An incomplete document validates and is written
          (ADR-0043).
        """
        with self.lock(name):
            if not self.is_free(name):
                raise ListingNameTaken(name)
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
        text = yaml.safe_dump(canonical_document(document), sort_keys=False, allow_unicode=True)
        write_bytes_atomic(path, text.encode("utf-8"))
        return path
