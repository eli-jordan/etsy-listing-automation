"""The workspace's keyed locks: one per listing, mockup template and listing
template, shared by everything in the process that names it.

Contention is made with a held lock and a second thread, not left to timing.
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import get_args

import pytest

from etsy_listings.core.workspace import locks
from etsy_listings.core.workspace.locks import LockDomain
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace

DOMAINS: tuple[LockDomain, ...] = get_args(LockDomain)
WAITS = 0.2


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _blocks(
    held: AbstractContextManager[None], wanted: Callable[[], AbstractContextManager[None]]
) -> bool:
    """Does a second thread wait for ``wanted`` while ``held`` is held?
    It always gets it once ``held`` is released."""
    entered = threading.Event()

    def take() -> None:
        with wanted():
            entered.set()

    with held:
        waiting = threading.Thread(target=take)
        waiting.start()
        blocked = not entered.wait(WAITS)
    waiting.join(timeout=5)
    assert entered.is_set(), "the waiting thread never got the lock"
    return blocked


@pytest.mark.parametrize("domain", DOMAINS)
class TestOneName:
    def test_a_second_thread_waits_for_it(self, workspace: Workspace, domain: LockDomain) -> None:
        assert _blocks(
            locks.hold(workspace, domain, "hike"), lambda: locks.hold(workspace, domain, "hike")
        )

    def test_a_holder_may_take_it_again(self, workspace: Workspace, domain: LockDomain) -> None:
        with locks.hold(workspace, domain, "hike"), locks.hold(workspace, domain, "hike", "other"):
            pass

    def test_names_differing_only_in_case_share_it(
        self, workspace: Workspace, domain: LockDomain
    ) -> None:
        """Windows makes them one directory."""
        assert _blocks(
            locks.hold(workspace, domain, "hike"), lambda: locks.hold(workspace, domain, "HIKE")
        )

    def test_another_name_does_not_wait(self, workspace: Workspace, domain: LockDomain) -> None:
        assert not _blocks(
            locks.hold(workspace, domain, "hike"), lambda: locks.hold(workspace, domain, "camp")
        )

    def test_refuses_a_name_that_is_not_a_path_segment(
        self, workspace: Workspace, domain: LockDomain
    ) -> None:
        with pytest.raises(InvalidNameError), locks.hold(workspace, domain, "hike", "../escape"):
            pass
        # Refused before anything was taken: another thread gets "hike" at once.
        assert not _blocks(
            locks.hold(workspace, domain, "camp"), lambda: locks.hold(workspace, domain, "hike")
        )


class TestScope:
    def test_every_workspace_over_one_root_shares_it(self, workspace_root: Path) -> None:
        """The engine, the editor and batch creation each open their own."""
        one = Workspace.discover(root_override=workspace_root)
        other = Workspace.discover(root_override=workspace_root)

        assert _blocks(
            locks.hold(one, "listing", "hike"), lambda: locks.hold(other, "listing", "hike")
        )

    def test_another_workspace_root_does_not_wait(
        self, workspace: Workspace, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        shutil.copytree(workspace.root, elsewhere)
        other = Workspace.discover(root_override=elsewhere)

        assert not _blocks(
            locks.hold(workspace, "listing-template", "hike"),
            lambda: locks.hold(other, "listing-template", "hike"),
        )

    def test_one_name_in_two_domains_is_two_locks(self, workspace: Workspace) -> None:
        """A listing and the listing template it came from may share a name."""
        assert not _blocks(
            locks.hold(workspace, "listing", "hike"),
            lambda: locks.hold(workspace, "listing-template", "hike"),
        )


class TestSeveralNames:
    def test_holds_every_name_it_was_given(self, workspace: Workspace) -> None:
        assert _blocks(
            locks.hold(workspace, "listing", "hike", "camp"),
            lambda: locks.hold(workspace, "listing", "camp"),
        )

    def test_opposite_orders_in_two_threads_do_not_deadlock(self, workspace: Workspace) -> None:
        """A rename of a to b racing one of b to a: both are taken in one order."""
        rounds = 200
        done = [0, 0]

        def churn(slot: int, *names: str) -> None:
            for _ in range(rounds):
                with locks.hold(workspace, "listing-template", *names):
                    done[slot] += 1

        threads = [
            threading.Thread(target=churn, args=(0, "hike", "Camp")),
            threading.Thread(target=churn, args=(1, "camp", "HIKE")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert done == [rounds, rounds]
