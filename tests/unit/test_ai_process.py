"""``ai/process.py``: the cross-platform subprocess-tree launch/cleanup
helper both CLI adapters (`ai/codex.py`, `ai/claude.py`) run their child
process through (AI SEO implementation plan, PR4, item 5: "process-tree
cleanup for timeouts, cancellation, and request disconnects").

Most tests here replace `etsy_listings.ai.process.subprocess.Popen` with a
hand-rolled double -- never a real child process -- so this suite proves the
*launch and cleanup wiring* (process-group flags, what gets killed and how,
on which platform) without depending on timing or an actual hung process.

The "real process tree" section at the bottom is deliberately different: it
launches genuine `sys.executable` child *and grandchild* processes (never
`codex`/`claude` -- no provider CLI, no cost, no network) and asserts they
are actually dead afterwards, by checking OS-visible liveness rather than a
mock's call log. The mocked tests above prove the wiring is correct; these
prove the wiring's actual effect on a real OS process tree -- the specific
gap a double covering only `_kill_process_tree`'s call site cannot close,
since a mock recording "I was asked to kill pid 4321" never proves pid 4321
(or anything it spawned) is actually gone.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.ai import process
from etsy_listings.ai.models import Deadline


class FakePopen:
    """A `subprocess.Popen` double whose `communicate()` blocks until either
    the test lets it finish (`finish()`) or something kills it -- exactly the
    two ways a real child ends. Records every constructor and kill-path call
    for a test to assert on.
    """

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 4321
        self._done = threading.Event()
        self._returncode: int | None = None
        self._stdout = ""
        self._stderr = ""
        self.terminated = False
        self.killed = False
        self.stdin_received: str | None = None

    def finish(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._done.set()

    def communicate(self, input: str | None = None) -> tuple[str, str]:  # noqa: A002
        self.stdin_received = input
        self._done.wait(timeout=5.0)
        if not self._done.is_set():  # pragma: no cover - defensive, should not happen
            raise AssertionError("FakePopen.communicate() was never released")
        return self._stdout, self._stderr

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        # A real kill eventually unblocks `communicate()` -- simulate that so
        # the worker thread this module starts actually finishes.
        if not self._done.is_set():
            self.finish(returncode=-9)


@pytest.fixture
def fake_popen(monkeypatch: pytest.MonkeyPatch) -> list[FakePopen]:
    created: list[FakePopen] = []

    def factory(argv: list[str], **kwargs: Any) -> FakePopen:
        proc = FakePopen(argv, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(process.subprocess, "Popen", factory)
    return created


def test_run_managed_returns_completed_output(fake_popen: list[FakePopen]) -> None:
    def _complete() -> None:
        time.sleep(0.01)
        fake_popen[0].finish(returncode=0, stdout="hello", stderr="")

    threading.Thread(target=_complete).start()

    result = process.run_managed(
        ["codex", "exec"],
        cwd=Path("/workspace"),
        input_text="prompt text",
        deadline=Deadline.starting_now(seconds=60),
        poll_interval=0.01,
    )

    assert result.returncode == 0
    assert result.stdout == "hello"
    assert result.timed_out is False
    assert result.cancelled is False
    assert fake_popen[0].stdin_received == "prompt text"


def test_run_managed_passes_cwd_and_argv(fake_popen: list[FakePopen]) -> None:
    def _complete() -> None:
        time.sleep(0.01)
        fake_popen[0].finish(returncode=0)

    threading.Thread(target=_complete).start()

    process.run_managed(
        ["claude", "-p", "hi"],
        cwd=Path("/some/workspace"),
        input_text="",
        deadline=Deadline.starting_now(seconds=60),
        poll_interval=0.01,
    )

    assert fake_popen[0].argv == ["claude", "-p", "hi"]
    assert fake_popen[0].kwargs["cwd"] == str(Path("/some/workspace"))


def test_run_managed_kills_the_process_tree_on_timeout(
    fake_popen: list[FakePopen], monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_pids: list[int] = []
    monkeypatch.setattr(
        process, "_kill_process_tree", lambda proc: killed_pids.append(proc.pid) or proc.kill()
    )

    already_expired = Deadline(deadline_at=time.monotonic() - 1)

    result = process.run_managed(
        ["codex", "exec"],
        cwd=Path("/workspace"),
        input_text="prompt",
        deadline=already_expired,
        poll_interval=0.01,
    )

    assert result.timed_out is True
    assert result.cancelled is False
    assert killed_pids == [fake_popen[0].pid]


def test_run_managed_kills_the_process_tree_on_cancellation(
    fake_popen: list[FakePopen], monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_pids: list[int] = []
    monkeypatch.setattr(
        process, "_kill_process_tree", lambda proc: killed_pids.append(proc.pid) or proc.kill()
    )
    cancel_event = threading.Event()
    cancel_event.set()

    result = process.run_managed(
        ["codex", "exec"],
        cwd=Path("/workspace"),
        input_text="prompt",
        deadline=Deadline.starting_now(seconds=60),
        cancel_event=cancel_event,
        poll_interval=0.01,
    )

    assert result.cancelled is True
    assert result.timed_out is False
    assert killed_pids == [fake_popen[0].pid]


def test_run_managed_does_not_kill_a_process_that_finishes_in_time(
    fake_popen: list[FakePopen], monkeypatch: pytest.MonkeyPatch
) -> None:
    killed_pids: list[int] = []
    monkeypatch.setattr(process, "_kill_process_tree", lambda proc: killed_pids.append(proc.pid))

    def _complete() -> None:
        time.sleep(0.01)
        fake_popen[0].finish(returncode=0, stdout="ok")

    threading.Thread(target=_complete).start()

    result = process.run_managed(
        ["codex", "exec"],
        cwd=Path("/workspace"),
        input_text="prompt",
        deadline=Deadline.starting_now(seconds=60),
        poll_interval=0.01,
    )

    assert result.returncode == 0
    assert killed_pids == []


def test_run_managed_raises_cli_process_error_when_the_binary_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def factory(argv: list[str], **kwargs: Any) -> FakePopen:
        raise FileNotFoundError("no such file: codex")

    monkeypatch.setattr(process.subprocess, "Popen", factory)

    with pytest.raises(process.CliProcessError):
        process.run_managed(
            ["codex", "exec"],
            cwd=Path("/workspace"),
            input_text="prompt",
            deadline=Deadline.starting_now(seconds=60),
        )


def test_new_process_group_kwargs_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process.sys, "platform", "linux")
    assert process._new_process_group_kwargs() == {"start_new_session": True}


def test_new_process_group_kwargs_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process.sys, "platform", "win32")
    # `subprocess.CREATE_NEW_PROCESS_GROUP` does not exist as a real
    # attribute on a POSIX host at all, so this compares against the same
    # defensively-resolved constant `_new_process_group_kwargs` itself uses
    # (`process._CREATE_NEW_PROCESS_GROUP`), not the module attribute
    # directly -- mirrors `process._SIGKILL` below for the opposite platform.
    assert process._new_process_group_kwargs() == {
        "creationflags": process._CREATE_NEW_PROCESS_GROUP
    }


def test_kill_process_tree_uses_taskkill_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process.sys, "platform", "win32")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        process.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(list(argv)),
    )

    class _Proc:
        pid = 999

        def kill(self) -> None:
            pass

    process._kill_process_tree(_Proc())  # type: ignore[arg-type]

    assert calls == [["taskkill", "/T", "/F", "/PID", "999"]]


def test_kill_process_tree_uses_killpg_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process.sys, "platform", "linux")
    calls: list[tuple[int, int]] = []
    # `os.getpgid`/`os.killpg` do not exist as attributes on a native Windows
    # `os` module at all, so this dev/CI host may need `raising=False` to
    # patch them in for the duration of the test even though the code under
    # test only ever calls them on the (here, simulated) POSIX branch.
    monkeypatch.setattr(process.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(
        process.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)), raising=False
    )

    class _Proc:
        pid = 555

        def kill(self) -> None:
            pass

    process._kill_process_tree(_Proc())  # type: ignore[arg-type]

    assert calls == [(555, process._SIGKILL)]


# ---------------------------------------------------- real process tree

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
        deadline=Deadline.starting_now(seconds=1.5),
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

    def _cancel_soon() -> None:
        _wait_for_file_to_appear(grandchild_marker, timeout=5.0)
        cancel_event.set()

    canceller = threading.Thread(target=_cancel_soon)
    canceller.start()

    result = process.run_managed(
        argv,
        cwd=tmp_path,
        input_text="",
        deadline=Deadline.starting_now(seconds=60),
        cancel_event=cancel_event,
        poll_interval=0.02,
    )
    canceller.join(timeout=5.0)

    assert result.cancelled is True
    _assert_stopped_growing(child_marker, settle=0.5)
    _assert_stopped_growing(grandchild_marker, settle=0.5)


def test_kill_process_tree_on_posix_survives_a_process_that_already_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process.sys, "platform", "linux")

    def _raise(pid: int) -> int:
        raise ProcessLookupError()

    def _unexpected_killpg(pgid: int, sig: int) -> None:
        raise AssertionError("killpg must not be called once getpgid raises")

    monkeypatch.setattr(process.os, "getpgid", _raise, raising=False)
    # `os.killpg` is merely *referenced* (attribute lookup) while Python
    # resolves the call `os.killpg(os.getpgid(...), ...)`, even though
    # `os.getpgid(...)` raising means it is never actually invoked -- a
    # native Windows `os` module has no such attribute at all, so it needs
    # patching in here too, purely so the reference itself resolves.
    monkeypatch.setattr(process.os, "killpg", _unexpected_killpg, raising=False)

    class _Proc:
        pid = 555

        def kill(self) -> None:
            pass

    process._kill_process_tree(_Proc())  # type: ignore[arg-type]
