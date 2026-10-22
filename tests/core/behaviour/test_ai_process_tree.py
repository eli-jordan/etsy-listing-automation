"""``ai/process.py`` against real operating-system processes (T13).

These launch genuine `sys.executable` child *and grandchild* processes (never
`codex`/`claude` -- no provider CLI, no cost, no network) and assert they are
actually dead afterwards, by checking OS-visible liveness rather than a
double's call log. The wiring itself -- which flags, which kill call, on which
platform -- is ``tests/core/unit/test_ai_process.py``'s, against a fake
`Popen`; a double recording "I was asked to kill pid 4321" never proves pid
4321, or anything it spawned, is gone. That is this subject's job, along with
UTF-8 crossing a real pipe whatever the locale.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from etsy_listings.core.ai import process
from etsy_listings.core.ai.models import Deadline

from tests.support.gates import workers

_GRANDCHILD_SCRIPT = (
    "import sys, time\n"
    "marker = sys.argv[1]\n"
    "while True:\n"
    "    with open(marker, 'a') as f:\n"
    "        f.write('x')\n"
    "    time.sleep(0.05)\n"
)

_CHILD_SCRIPT = (
    "import subprocess, sys, time\n"
    "grandchild_script, grandchild_marker, child_marker = sys.argv[1:4]\n"
    "subprocess.Popen([sys.executable, '-c', grandchild_script, grandchild_marker])\n"
    "while True:\n"
    "    with open(child_marker, 'a') as f:\n"
    "        f.write('x')\n"
    "    time.sleep(0.05)\n"
)
"""Two genuine (never-terminating, so a graceful exit can never race the
kill) `sys.executable` scripts -- never `codex`/`claude`, no provider CLI, no
cost. The child spawns the grandchild as an ordinary subprocess (no
`start_new_session` of its own), so it inherits whatever process group/tree
`run_managed` placed the child into -- exactly the shape a coding-agent CLI
spawning its own helper process takes, and exactly what a plain
`proc.kill()` (the direct child only) would leave running."""


def _wait_for_file_to_appear(path: Path, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return
        time.sleep(0.02)
    raise AssertionError(f"{path} never appeared -- the process tree never started writing")


def _assert_stopped_growing(path: Path, *, settle: float) -> None:
    size_before = path.stat().st_size
    time.sleep(settle)
    size_after = path.stat().st_size
    assert size_after == size_before, (
        f"{path} grew from {size_before} to {size_after} bytes after the kill -- "
        "the process that writes it is still alive"
    )


@dataclass(frozen=True)
class _ExpiresOnceWritten(Deadline):
    """A deadline that passes only once every marker has been written -- so
    the tree it kills is known to be up -- or after a generous safety budget,
    when the assertions below say what never started.

    A fixed 1.5 s deadline raced the process tree's own start: under a
    loaded full-suite run two interpreter start-ups (the child, then the
    grandchild it spawns) can take longer than that, the kill landed before
    the grandchild existed, and the test failed with "never appeared". The
    cancellation test already waits for the grandchild; this is the timeout
    path's equivalent."""

    markers: tuple[Path, ...] = ()
    safety_at: float = field(default_factory=lambda: time.monotonic() + 30.0)

    @property
    def expired(self) -> bool:
        if time.monotonic() > self.safety_at:
            return True
        return all(m.is_file() and m.stat().st_size > 0 for m in self.markers)


def test_run_managed_actually_kills_a_real_process_and_its_grandchild_on_timeout(
    tmp_path: Path,
) -> None:
    grandchild_marker = tmp_path / "grandchild_alive.txt"
    child_marker = tmp_path / "child_alive.txt"
    argv = [
        sys.executable,
        "-c",
        _CHILD_SCRIPT,
        _GRANDCHILD_SCRIPT,
        str(grandchild_marker),
        str(child_marker),
    ]

    result = process.run_managed(
        argv,
        cwd=tmp_path,
        input_text="",
        deadline=_ExpiresOnceWritten(markers=(child_marker, grandchild_marker)),
        poll_interval=0.02,
    )

    assert result.timed_out is True

    # Both scripts loop forever, writing every 0.05s, until killed -- so
    # each marker file existing at all already proves the child and the
    # grandchild it spawned were both alive at some point.
    _wait_for_file_to_appear(child_marker, timeout=5.0)
    _wait_for_file_to_appear(grandchild_marker, timeout=5.0)

    # And neither file grows any further once `run_managed` has returned --
    # proof the whole tree (not just the direct child `_kill_process_tree`
    # was handed) is actually dead, not merely that a mock was asked to kill
    # it.
    _assert_stopped_growing(child_marker, settle=0.5)
    _assert_stopped_growing(grandchild_marker, settle=0.5)


def test_run_managed_actually_kills_a_real_process_tree_on_cancellation(
    tmp_path: Path,
) -> None:
    grandchild_marker = tmp_path / "grandchild_alive.txt"
    child_marker = tmp_path / "child_alive.txt"
    argv = [
        sys.executable,
        "-c",
        _CHILD_SCRIPT,
        _GRANDCHILD_SCRIPT,
        str(grandchild_marker),
        str(child_marker),
    ]
    cancel_event = threading.Event()

    def _cancel_once_up() -> None:
        try:
            _wait_for_file_to_appear(grandchild_marker, timeout=30.0)
        finally:
            cancel_event.set()  # never leave run_managed waiting on its deadline

    with workers() as start:
        canceller = start("canceller", _cancel_once_up)
        result = process.run_managed(
            argv,
            cwd=tmp_path,
            input_text="",
            deadline=Deadline.starting_now(seconds=60),
            cancel_event=cancel_event,
            poll_interval=0.02,
        )
        canceller.result()  # the grandchild was up before the cancel

    assert result.cancelled is True
    _assert_stopped_growing(child_marker, settle=0.5)
    _assert_stopped_growing(grandchild_marker, settle=0.5)


def test_run_managed_speaks_utf8_to_a_real_process_whatever_the_locale(tmp_path: Path) -> None:
    # The proposal prompt carries Etsy listing titles verbatim (the market
    # block), and those hold characters a Windows ANSI code page cannot
    # encode. The CLIs read and write UTF-8; the locale's code page is
    # neither here nor there.
    text = "Retro tee ✓ 日本語 — café 🏔️"
    echo = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"

    result = process.run_managed(
        [sys.executable, "-c", echo],
        cwd=tmp_path,
        input_text=text,
        deadline=Deadline.starting_now(seconds=30),
        poll_interval=0.02,
    )

    assert result.returncode == 0
    assert result.stdout == text
