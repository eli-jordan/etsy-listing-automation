"""Cross-platform subprocess-tree launch and cleanup for the local CLI
adapters (AI SEO implementation plan, PR4, item 5: "process-tree cleanup for
timeouts, cancellation, and request disconnects").

Both the Codex and Claude adapters shell out to a coding-agent CLI that may
itself spawn helper processes. A plain `subprocess.run(..., timeout=...)`
only reaps the direct child on a timeout -- any grandchild is left running.
`run_managed` instead launches the child in its own process group/session
(:func:`_new_process_group_kwargs`) so the whole tree can be killed as one
unit (:func:`_kill_process_tree`), and races that kill against three
independent stop conditions rather than one:

- the shared request `Deadline` expiring (a timeout),
- an external `threading.Event` being set (cancellation -- the editor was
  left, or a browser disconnect PR5's API layer detected), and
- the child simply finishing on its own.

Only the last one is not a kill. Every adapter call goes through this one
function so "what gets terminated, and how" lives in exactly one place
rather than being reimplemented per provider.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etsy_listings.ai.models import Deadline

_DEFAULT_POLL_INTERVAL = 0.05
"""How often the polling loop below wakes up to check the deadline and the
cancellation event. Small enough that a 60-second deadline is honoured to
within a fraction of a second; large enough not to spin the CPU."""

_REAP_TIMEOUT = 5.0
"""How long `run_managed` waits for the worker thread to notice a kill and
return, once `_kill_process_tree` has been asked to end the child. A real
process dies from SIGKILL/`taskkill /F` almost immediately; this is a ceiling
against a pathological case, not the expected wait."""

_SIGKILL = getattr(signal, "SIGKILL", 9)
"""`signal.SIGKILL` does not exist in Python's `signal` module on Windows --
referencing it there raises `AttributeError` even though this module only
ever *calls* it on the POSIX branch below. Resolved once, defensively, with
`os.kill`'s own numeric fallback (9), so importing this module never depends
on which platform it happens to run on."""

_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
"""Mirrors `_SIGKILL`'s reasoning for the opposite platform:
`subprocess.CREATE_NEW_PROCESS_GROUP` does not exist on POSIX. `0x00000200`
is that flag's own documented numeric value on Windows, used only as a
fallback that is never actually reached there."""


class CliProcessError(RuntimeError):
    """The child process could not even be started -- the executable is
    missing, not executable, or the OS refused to launch it. Distinct from a
    process that started and then exited non-zero, which is a normal,
    classifiable `ProcessResult`, not this exception."""


@dataclass(frozen=True)
class ProcessResult:
    """What happened when a managed subprocess ran to completion, timed out,
    or was cancelled.

    ``returncode`` is `None` only if the process could not be reaped after a
    kill (should not happen on a real OS, but a caller must not assume it is
    always an int). ``stdout``/``stderr`` hold whatever was captured before a
    kill interrupted `communicate()` -- possibly empty, never partial-decoded
    garbage, since `subprocess` reads text incrementally as valid text.
    """

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    cancelled: bool


def _new_process_group_kwargs() -> dict[str, Any]:
    """The `subprocess.Popen` kwarg that puts the child in its own process
    group (POSIX) or process group (Windows), so `_kill_process_tree` can
    terminate it and everything it spawned without also touching this
    process's own group."""
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _posix_descendant_pids(pid: int) -> list[int]:
    """Every live descendant of ``pid``, found by walking `/proc`'s PPID
    links rather than trusting process-group signal delivery alone.

    `killpg` assumes every descendant is still a member of the group it was
    forked into -- true by POSIX semantics, but some sandboxed/containerized
    kernels have a registration race where a grandchild forked moments
    before the kill is not yet visible to the group-wide signal delivery
    path, so the group kill reaches the direct child but misses it. Reading
    `/proc` directly for "whose PPid is this" sidesteps that: it is the same
    ancestry `taskkill /T` (below) already reads on Windows via a different
    API. Returns ``[]`` on a kernel with no `/proc` (e.g. macOS) -- `killpg`
    is the only path there.
    """
    try:
        pids = [entry for entry in os.listdir("/proc") if entry.isdigit()]
    except OSError:
        return []
    children_of: dict[int, list[int]] = {}
    for entry in pids:
        try:
            stat = Path("/proc", entry, "stat").read_text()
        except OSError:
            continue
        # The 2nd field (`comm`) is parenthesised and may itself contain
        # spaces/parens, so only the 3rd field onward is safe to split on
        # whitespace; PPid is the first of those.
        fields_after_comm = stat.rsplit(")", 1)[-1].split()
        ppid = int(fields_after_comm[1])
        children_of.setdefault(ppid, []).append(int(entry))

    descendants: list[int] = []
    frontier = [pid]
    while frontier:
        frontier = [child for parent in frontier for child in children_of.get(parent, [])]
        descendants.extend(frontier)
    return descendants


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    """Best-effort termination of ``proc`` and its whole process tree.

    Windows has no `killpg` equivalent for an arbitrary `Popen`; `taskkill
    /T /F` (terminate the tree, forcefully) against the process group leader
    it was launched into (:func:`_new_process_group_kwargs`) is the
    documented way to reach children a coding-agent CLI spawned. POSIX kills
    the whole process group with `SIGKILL` via the same group, *and* SIGKILLs
    each descendant `/proc` still reports individually
    (:func:`_posix_descendant_pids`), since the group kill alone can race a
    freshly-forked grandchild on some sandboxed kernels. Either path also
    calls `proc.kill()` directly, both as a fallback if the tree kill could
    not find the process (already exited) and because it is what marks
    `Popen` itself as reaped.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        descendants = _posix_descendant_pids(proc.pid)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), _SIGKILL)
        for pid in descendants:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, _SIGKILL)
    with contextlib.suppress(Exception):
        proc.kill()


def run_managed(
    argv: Sequence[str],
    *,
    cwd: Path,
    input_text: str,
    deadline: Deadline,
    cancel_event: threading.Event | None = None,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
) -> ProcessResult:
    """Launch ``argv`` as a managed child process, write ``input_text`` to
    its stdin, and wait for it to finish, the shared ``deadline`` to expire,
    or ``cancel_event`` to be set -- whichever comes first.

    A caller (a `SeoProvider` adapter) never has to reason about process
    groups, `taskkill` vs `killpg`, or how to race a blocking `communicate()`
    against an external stop signal; it gets back one `ProcessResult` and
    classifies ``timed_out``/``cancelled``/``returncode`` into whatever
    provider-specific error it raises.
    """
    try:
        proc = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **_new_process_group_kwargs(),
        )
    except OSError as exc:
        raise CliProcessError(f"could not start {list(argv)!r}: {exc}") from exc

    captured: dict[str, str] = {}

    def _communicate() -> None:
        stdout, stderr = proc.communicate(input=input_text)
        captured["stdout"] = stdout
        captured["stderr"] = stderr

    worker = threading.Thread(target=_communicate, daemon=True)
    worker.start()

    timed_out = False
    cancelled = False
    while worker.is_alive():
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        if deadline.expired:
            timed_out = True
            break
        worker.join(timeout=poll_interval)

    if timed_out or cancelled:
        _kill_process_tree(proc)
        worker.join(timeout=_REAP_TIMEOUT)

    return ProcessResult(
        returncode=proc.poll(),
        stdout=captured.get("stdout", ""),
        stderr=captured.get("stderr", ""),
        timed_out=timed_out,
        cancelled=cancelled,
    )
