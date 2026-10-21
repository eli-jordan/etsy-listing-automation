"""CPU phase priority remains workspace-scoped and cancellation-aware."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from etsy_listings.core.application.preparation.activity import interactive, yield_to_interactive
from etsy_listings.core.workspace import Workspace


def test_background_waits_for_all_foreground_requests_and_still_checks_cancellation(workspace_root):
    workspace = Workspace.discover(root_override=workspace_root)
    checked = Event()
    cancel = Event()

    def check():
        checked.set()
        if cancel.is_set():
            raise RuntimeError("cancelled")

    with ThreadPoolExecutor() as pool, interactive(workspace):
        with interactive(workspace):
            waiting = pool.submit(yield_to_interactive, workspace, check)
            assert checked.wait(1)
            assert not waiting.done()
        assert not waiting.done()
        cancel.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            waiting.result(timeout=1)
    yield_to_interactive(workspace, lambda: None)


def test_foreground_exception_releases_background_and_other_workspaces_are_independent(
    workspace_root, tmp_path
):
    workspace = Workspace.discover(root_override=workspace_root)
    other_root = tmp_path / "other"
    other_root.mkdir()
    (other_root / "shop.yaml").write_text("etsy: {currency: USD}")
    other = Workspace.discover(root_override=other_root)
    with ThreadPoolExecutor() as pool:
        with pytest.raises(ValueError, match="preview failed"), interactive(workspace):
            pool.submit(yield_to_interactive, other, lambda: None).result(timeout=1)
            waiting = pool.submit(yield_to_interactive, workspace, lambda: None)
            raise ValueError("preview failed")
        waiting.result(timeout=1)
