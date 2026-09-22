"""``ai/process.py``: the cross-platform subprocess-tree launch/cleanup
helper both CLI adapters (`ai/codex.py`, `ai/claude.py`) run their child
process through (AI SEO implementation plan, PR4, item 5: "process-tree
cleanup for timeouts, cancellation, and request disconnects").

Every test here replaces `etsy_listings.ai.process.subprocess.Popen` with a
hand-rolled double -- never a real child process -- so this suite proves the
*launch and cleanup wiring* (process-group flags, what gets killed and how,
on which platform) without depending on timing or an actual hung process.
"""

from __future__ import annotations

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
