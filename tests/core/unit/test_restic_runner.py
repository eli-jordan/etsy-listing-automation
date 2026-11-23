"""The streaming restic runner (workspace-backup plan, PR 2 and P6).

Driven through a scripted launcher that replays restic's real ``--json``
lines: each exit code becomes a typed error carrying restic's message, cancel
stops the process, and the password reaches restic only through its
environment.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from etsy_listings.core.backup.restic import (
    RepositoryLockedError,
    RepositoryNotFoundError,
    Restic,
    ResticCancelledError,
    ResticError,
    Snapshot,
    WrongPasswordError,
    launch_process,
)

from tests.support.restic import Reply, ScriptedRestic, exit_error

PASSWORD = "correct horse battery staple"
BINARY = Path("/opt/restic/restic")
REPOSITORY = Path("/srv/backups")

SNAPSHOT_LINE = [
    {
        "time": "2026-11-23T20:13:10.6584313+01:00",
        "tree": "cfbbd529e5e8fb9bebbf006fc93ce7124eb526a1c421b3c806744df666805783",
        "paths": ["C:\\Users\\Admin\\naturally-inked-studio-workspace"],
        "hostname": "ELISDESKTOP",
        "username": "ELISDESKTOP\\Admin",
        "program_version": "restic 0.19.1",
        "summary": {"total_files_processed": 1204, "total_bytes_processed": 20480},
        "id": "e12483c71eeb33dd5fcd79de1c0f5efc3348aba5923d8166133e4508620d9f2e",
        "short_id": "e12483c7",
    }
]


def _restic(*replies: Reply) -> tuple[Restic, ScriptedRestic]:
    launcher = ScriptedRestic(*replies)
    return Restic(BINARY, REPOSITORY, PASSWORD, launch=launcher), launcher


def test_a_command_streams_each_json_line_as_it_arrives() -> None:
    status = {"message_type": "status", "percent_done": 0.5}
    summary = {"message_type": "summary", "snapshot_id": "e12483c7"}
    restic, launcher = _restic(Reply(stdout=[status, summary]))

    assert list(restic.stream("backup", "/workspace")) == [status, summary]
    assert launcher.launches[0].argv == [
        str(BINARY),
        "--repo",
        str(REPOSITORY),
        "--json",
        "backup",
        "/workspace",
    ]


def test_lines_that_are_not_json_are_skipped() -> None:
    restic, _ = _restic(Reply(stdout=["unexpected banner", {"message_type": "summary"}]))

    assert list(restic.stream("check")) == [{"message_type": "summary"}]


def test_the_password_reaches_restic_only_through_its_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A password file or command inherited from the shell would make restic
    refuse to start, or open the repository with someone else's key."""
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", "/elsewhere")
    monkeypatch.setenv("RESTIC_PASSWORD_COMMAND", "pass show restic")
    monkeypatch.setenv("RESTIC_REPOSITORY", "/another/repository")
    restic, launcher = _restic(Reply(stdout=[[]]))

    restic.snapshots()

    launch = launcher.launches[0]
    assert launch.env["RESTIC_PASSWORD"] == PASSWORD
    assert not {"RESTIC_PASSWORD_FILE", "RESTIC_PASSWORD_COMMAND", "RESTIC_REPOSITORY"} & set(
        launch.env
    )
    assert all(PASSWORD not in argument for argument in launch.argv)


def test_the_password_never_appears_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    """restic does not echo the password, but its messages quote whatever it
    was given; a message that did would be redacted, not repeated."""
    caplog.set_level(logging.DEBUG)
    restic, _ = _restic(Reply(stderr=exit_error(1, f"Fatal: bad flag {PASSWORD}"), exit_code=1))

    with pytest.raises(ResticError) as caught:
        list(restic.stream("snapshots"))

    assert "restic" in caplog.text
    assert PASSWORD not in caplog.text
    assert PASSWORD not in str(caught.value)
    assert "Fatal: bad flag" in str(caught.value)
    assert PASSWORD not in repr(restic)


@pytest.mark.parametrize(
    ("code", "message", "error"),
    [
        (12, "Fatal: wrong password or no key found", WrongPasswordError),
        (
            10,
            "Fatal: repository does not exist: unable to open config file\n"
            "Is there a repository at the following location?\n/srv/backups",
            RepositoryNotFoundError,
        ),
        (
            11,
            "Fatal: unable to create lock in backend: repository is already locked",
            RepositoryLockedError,
        ),
        (
            1,
            "Fatal: create repository at /srv/backups failed: config file already exists",
            ResticError,
        ),
    ],
    ids=["wrong-password", "not-a-repository", "locked", "other-fatal"],
)
def test_each_exit_code_becomes_its_error_with_restics_message(
    code: int, message: str, error: type[ResticError]
) -> None:
    restic, _ = _restic(Reply(stderr="noise\n" + exit_error(code, message), exit_code=code))

    with pytest.raises(error) as caught:
        list(restic.stream("snapshots"))

    assert type(caught.value) is error
    assert caught.value.exit_code == code
    assert message.splitlines()[0] in str(caught.value)


def test_a_failure_without_a_json_message_keeps_the_end_of_stderr() -> None:
    restic, _ = _restic(Reply(stderr="panic: runtime error\ngoroutine 1", exit_code=2))

    with pytest.raises(ResticError, match="goroutine 1"):
        list(restic.stream("check"))


def test_a_binary_that_cannot_start_is_reported_by_path() -> None:
    def missing(argv: object, env: object) -> None:
        raise FileNotFoundError(2, "No such file or directory")

    restic = Restic(BINARY, REPOSITORY, PASSWORD, launch=missing)  # type: ignore[arg-type]  # -- a launcher that always fails

    with pytest.raises(ResticError, match="restic"):
        list(restic.stream("snapshots"))


def test_cancel_stops_the_process_and_says_so() -> None:
    cancel = threading.Event()
    restic, launcher = _restic(Reply(stdout=[{"message_type": "status"}], hang=True))
    lines = restic.stream("backup", "/workspace", cancel=cancel)

    assert next(lines) == {"message_type": "status"}
    cancel.set()
    with pytest.raises(ResticCancelledError):
        list(lines)

    assert launcher.processes[0].stopped.is_set()


def test_a_cancel_after_the_command_finished_changes_nothing() -> None:
    cancel = threading.Event()
    restic, _ = _restic(Reply(stdout=[{"message_type": "summary"}]))

    assert list(restic.stream("check", cancel=cancel)) == [{"message_type": "summary"}]
    cancel.set()


def test_abandoning_the_stream_stops_the_process() -> None:
    restic, launcher = _restic(Reply(stdout=[{"message_type": "status"}], hang=True))
    lines = restic.stream("backup", "/workspace")

    next(lines)
    lines.close()

    assert launcher.processes[0].stopped.is_set()


def test_init_returns_the_new_repositorys_id() -> None:
    restic, launcher = _restic(
        Reply(stdout=[{"message_type": "initialized", "id": "62d06b01", "repository": "/srv"}])
    )

    assert restic.init() == "62d06b01"
    assert launcher.commands == [["init"]]


def test_snapshots_are_parsed_oldest_first() -> None:
    newer = {
        **SNAPSHOT_LINE[0],
        "time": "2026-11-24T08:00:00Z",
        "id": "f" * 64,
        "short_id": "ffffffff",
    }
    restic, launcher = _restic(Reply(stdout=[[newer, *SNAPSHOT_LINE]]))

    snapshots = restic.snapshots()

    assert launcher.commands == [["snapshots"]]
    assert [snapshot.short_id for snapshot in snapshots] == ["e12483c7", "ffffffff"]
    assert snapshots[0] == Snapshot(
        id="e12483c71eeb33dd5fcd79de1c0f5efc3348aba5923d8166133e4508620d9f2e",
        short_id="e12483c7",
        time=datetime(2026, 11, 23, 20, 13, 10, 658431, tzinfo=timezone(timedelta(hours=1))),
        paths=("C:\\Users\\Admin\\naturally-inked-studio-workspace",),
        hostname="ELISDESKTOP",
        files=1204,
        size=20480,
    )
    assert snapshots[1].time == datetime(2026, 11, 24, 8, tzinfo=UTC)


def test_snapshots_can_be_read_without_taking_a_lock() -> None:
    restic, launcher = _restic(Reply(stdout=[[]]))

    assert restic.snapshots(lock=False) == ()
    assert launcher.commands == [["--no-lock", "snapshots"]]


# ----------------------------------------------------------- the real launcher


def test_the_real_launcher_stops_a_running_process_promptly() -> None:
    """``launch_process`` owns a real child: stopping it must not wait for the
    child to finish on its own."""
    process = launch_process(
        [sys.executable, "-c", "import time; print('{}', flush=True); time.sleep(60)"],
        dict(os.environ),
    )
    lines = iter(process.stdout)
    assert next(lines).strip() == "{}"

    started = time.monotonic()
    process.stop()
    process.wait()

    assert time.monotonic() - started < 15
    assert list(lines) == []


def test_the_real_launcher_collects_stderr_and_the_exit_code() -> None:
    process = launch_process(
        [sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"],
        dict(os.environ),
    )

    assert [line.strip() for line in process.stdout] == ["out"]
    assert process.wait() == 3
    assert process.stderr() == "err"
