"""``RunContext.require_etsy`` -- the unwrap Phase 3's stages use, mirroring
`require_printify` for the same reason: `plan` builds a context for a
workspace that has never signed in to Etsy, so the field stays optional and
a stage that has got as far as applying needs a loud failure if it is absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.engine.context import MissingClientError

from tests.support.builders import a_context


def test_require_etsy_returns_the_configured_client(workspace_root: Path) -> None:
    client = FakeEtsyListingClient()
    ctx = a_context(workspace_root, etsy=client)

    assert ctx.require_etsy() is client


def test_require_etsy_without_one_configured_fails_loudly(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)

    with pytest.raises(MissingClientError, match="Etsy"):
        ctx.require_etsy()
