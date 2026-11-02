"""Managed ownership survives a launcher that has already exited."""

import os
import sys
import threading
import time

import pytest

from etsy_listings.core.ai.discovery import ModelDiscovery
from etsy_listings.core.ai.models import Deadline
from etsy_listings.core.ai.process import run_managed

from tests.support.cli_host import ScriptedCliHost
from tests.support.exited_launcher import ExitedLauncher

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not hasattr(os, "pidfd_open"),
    reason="process identities require Windows handles or Linux pidfds",
)


def test_discovery_reaps_an_exited_launchers_child_and_pipe_readers(tmp_path):
    with ExitedLauncher(tmp_path) as tree:
        # The real process owner, behind a machine where only `codex` is installed.
        host = ScriptedCliHost(installed={"codex": str(tree.command)}, managed={(): run_managed})

        def clock():
            return time.monotonic() + (16 if tree.exited() else 0)

        result = ModelDiscovery(monotonic=clock, host=host).read()
        assert result.providers["codex"].problem
        assert time.monotonic() - tree.started < 6
        tree.assert_clean()


@pytest.mark.parametrize("returncode", [0, 7])
@pytest.mark.parametrize("captured_pipes", [True, False])
def test_normal_or_error_exit_cleans_descendants_without_spending_the_deadline(
    tmp_path, returncode, captured_pipes
):
    with ExitedLauncher(tmp_path, returncode=returncode, captured_pipes=captured_pipes) as tree:

        def clock():
            tree.exited()  # Pin identities and release the launcher before it exits.
            return time.monotonic()

        result = run_managed(
            [str(tree.command)],
            cwd=tmp_path,
            input_text="",
            deadline=Deadline.starting_now(seconds=15, clock=clock),
        )
        assert result.returncode == returncode
        assert "synthetic" in result.stdout
        assert not result.timed_out
        assert not result.cancelled
        assert time.monotonic() - tree.started < 6
        tree.assert_clean()


def test_cancellation_after_launcher_exit_cleans_children_and_readers(tmp_path):
    with ExitedLauncher(tmp_path) as tree:

        class CancelAfterExit(threading.Event):
            def is_set(self):
                return tree.exited()

        result = run_managed(
            [str(tree.command)],
            cwd=tmp_path,
            input_text="",
            deadline=Deadline.starting_now(seconds=15),
            cancel_event=CancelAfterExit(),
        )
        assert result.cancelled
        assert not result.timed_out
        tree.assert_clean()


def test_timeout_after_launcher_exit_preserves_output_and_cleans_children(tmp_path):
    with ExitedLauncher(tmp_path) as tree:

        def clock():
            return time.monotonic() + (16 if tree.exited() else 0)

        result = run_managed(
            [str(tree.command)],
            cwd=tmp_path,
            input_text="",
            deadline=Deadline.starting_now(seconds=15, clock=clock),
        )
        assert result.timed_out
        assert not result.cancelled
        assert result.returncode == 0
        assert "synthetic" in result.stdout
        tree.assert_clean()
