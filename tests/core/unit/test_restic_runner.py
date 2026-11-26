"""The real restic adapter (workspace-backup plan, PR 2 and P6): each
repository operation's argv, and how restic's ``--json`` lines and exit
codes become the interface's figures, summaries and errors.

Driven through a scripted launcher that replays restic's real ``--json``
lines (restic 0.19.1's, trimmed to the keys read): each exit code becomes a
typed error carrying restic's message, cancel stops the process, and the
password reaches restic only through its environment. This and the tests
that run restic itself are the only ones that see argv; behaviour tests use
``tests/support/restic.py``'s in-memory repository.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.core.backup.repository import (
    BackupFigures,
    BackupSummary,
    RepositoryCheck,
    RepositoryLockedError,
    RepositoryNotFoundError,
    ResticCancelledError,
    ResticError,
    RestoreProgress,
    Snapshot,
    WrongPasswordError,
)
from etsy_listings.core.backup.restic import Restic, ResticProcess, launch_process
from etsy_listings.core.config.settings import RetentionSettings

PASSWORD = "correct horse battery staple"
BINARY = Path("/opt/restic/restic")
REPOSITORY = Path("/srv/backups")


# --------------------------------------------------- the scripted launcher

WORKSPACE_ID = "0f8d6c1e-4b7a-4f6e-9a39-2d4c5b1e7a90"


def exit_error(code: int, message: str) -> str:
    """restic's last stderr line when a command fails under ``--json``."""
    return json.dumps({"message_type": "exit_error", "code": code, "message": message})


@dataclass
class Reply:
    stdout: Sequence[Any] = ()
    """Each item is one stdout line: a string as is, anything else as JSON."""
    stderr: str = ""
    exit_code: int = 0
    hang: bool = False
    """Keep running after the last line until stopped, like a long backup."""


@dataclass
class Launch:
    argv: list[str]
    env: dict[str, str]


def _lines(lines: Sequence[Any]) -> Iterator[str]:
    for line in lines:
        yield (line if isinstance(line, str) else json.dumps(line)) + "\n"


@dataclass
class _Process:
    reply: Reply
    stopped: threading.Event = field(default_factory=threading.Event)

    @property
    def stdout(self) -> Iterator[str]:
        yield from _lines(self.reply.stdout)
        if self.reply.hang:
            deadline = time.monotonic() + 10
            while not self.stopped.wait(0.01):
                if time.monotonic() > deadline:
                    return

    def wait(self) -> int:
        if self.stopped.is_set():
            return 1
        return self.reply.exit_code

    def stderr(self) -> str:
        return self.reply.stderr

    def stop(self) -> None:
        self.stopped.set()


class ScriptedRestic:
    """The launcher: answers launches in order with ``replies``."""

    def __init__(self, *replies: Reply) -> None:
        self._replies = list(replies)
        self.launches: list[Launch] = []
        self.processes: list[_Process] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> ResticProcess:
        if not self._replies:
            raise AssertionError(f"restic was run more times than scripted: {list(argv)}")
        self.launches.append(Launch(list(argv), dict(env)))
        process = _Process(self._replies.pop(0))
        self.processes.append(process)
        return process

    @property
    def commands(self) -> list[list[str]]:
        """Each launch's argv after the binary and the global flags."""
        return [launch.argv[launch.argv.index("--json") + 1 :] for launch in self.launches]


def _restic(*replies: Reply) -> tuple[Restic, ScriptedRestic]:
    launcher = ScriptedRestic(*replies)
    return Restic(BINARY, REPOSITORY, PASSWORD, launch=launcher), launcher


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
SNAPSHOT_ID = "0d4f8513e5f5dcca2a2449d564c44f6bd0d367955d7cd12a9a6fda20efd1d717"
BACKUP_STATUS = {
    "message_type": "status",
    "percent_done": 0.5,
    "total_files": 10,
    "files_done": 5,
    "total_bytes": 1000,
    "bytes_done": 500,
}
BACKUP_SUMMARY = {
    "message_type": "summary",
    "files_new": 1,
    "snapshot_id": SNAPSHOT_ID,
    "data_added": 41_000_000,
}
RESTORE_STATUS = {
    "message_type": "status",
    "seconds_elapsed": 60,
    "percent_done": 0.25,
    "total_files": 400,
    "files_restored": 100,
    "total_bytes": 8_000_000,
    "bytes_restored": 2_000_000,
}
RESTORE_SUMMARY = {
    "message_type": "summary",
    "total_files": 400,
    "files_restored": 400,
    "total_bytes": 8_000_000,
    "bytes_restored": 8_000_000,
}


def _snapshot(*paths: str) -> Snapshot:
    return Snapshot(
        id="a" * 64,
        short_id="aaaaaaaa",
        time=datetime(2026, 11, 23, tzinfo=UTC),
        paths=paths,
        hostname="pc",
    )


# ---------------------------------------------------------- the commands


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


def test_a_cancelled_command_does_not_launch_restic() -> None:
    cancel = threading.Event()
    cancel.set()
    restic, launcher = _restic(Reply())

    with pytest.raises(ResticCancelledError):
        restic.prune(cancel=cancel)

    assert launcher.launches == []


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


# -------------------------------------------------------- the operations


def test_a_backup_names_the_folder_and_each_exclude_and_reports_progress() -> None:
    restic, launcher = _restic(Reply(stdout=[BACKUP_STATUS, BACKUP_SUMMARY]))
    heard: list[BackupFigures] = []

    folder = Path("/workspace")
    summary = restic.back_up(
        folder,
        workspace_id=WORKSPACE_ID,
        excludes=("*.tmp", ".cache/staging/*/upload.zip"),
        progress=heard.append,
    )

    assert launcher.commands == [
        [
            "backup",
            str(folder),
            "--tag",
            f"workspace:{WORKSPACE_ID}",
            "--exclude",
            "*.tmp",
            "--exclude",
            ".cache/staging/*/upload.zip",
        ]
    ]
    assert heard == [BackupFigures(files_done=5, files_total=10)]
    assert summary == BackupSummary(snapshot_id=SNAPSHOT_ID, data_added=41_000_000)


def test_a_backup_that_could_not_read_some_files_completes_with_warnings() -> None:
    """Exit code 3: the snapshot was made without the files it names."""
    unreadable = {
        "message_type": "error",
        "error": {"message": "The process cannot access the file"},
        "during": "archival",
        "item": "C:\\workspace\\runs.db",
    }
    restic, _ = _restic(
        Reply(
            stdout=[unreadable, BACKUP_SUMMARY],
            exit_code=3,
            stderr=exit_error(3, "Warning: at least one source file could not be read"),
        )
    )

    summary = restic.back_up(Path("/workspace"), workspace_id=WORKSPACE_ID)

    assert summary.snapshot_id == SNAPSHOT_ID
    assert summary.warnings == ("C:\\workspace\\runs.db: The process cannot access the file",)


def test_a_backup_that_made_no_snapshot_fails_even_on_exit_code_3() -> None:
    restic, _ = _restic(
        Reply(
            exit_code=3, stderr=exit_error(3, "Warning: at least one source file could not be read")
        )
    )

    with pytest.raises(ResticError, match="could not be read") as caught:
        restic.back_up(Path("/workspace"), workspace_id=WORKSPACE_ID)

    assert caught.value.exit_code == 3


def test_forget_keeps_only_this_workspace_s_snapshots_grouped_by_its_tag() -> None:
    """One more week and month than the retention names: restic counts the
    current ones. Grouped by the workspace tag, not host and paths."""
    restic, launcher = _restic(Reply(stdout=[[{"tags": [], "keep": [], "remove": None}]]))

    restic.forget(
        RetentionSettings(keep_within_days=7, weekly=4, monthly=3), workspace_id=WORKSPACE_ID
    )

    assert launcher.commands == [
        [
            "forget",
            "--tag",
            f"workspace:{WORKSPACE_ID}",
            "--group-by",
            "tags",
            "--keep-within",
            "7d",
            "--keep-weekly",
            "5",
            "--keep-monthly",
            "4",
        ]
    ]


def test_prune_runs_restic_prune() -> None:
    restic, launcher = _restic(Reply(stdout=["loading all snapshots...", "done"]))

    restic.prune()

    assert launcher.commands == [["prune"]]


def test_a_check_returns_its_verdict() -> None:
    restic, launcher = _restic(
        Reply(stdout=[{"message_type": "summary", "num_errors": 0}]),
        Reply(exit_code=1, stderr=exit_error(1, "pack 5f2b: not referenced in any index")),
        Reply(exit_code=11, stderr=exit_error(11, "repository is already locked")),
    )

    checks = [restic.check(), restic.check(), restic.check()]

    assert launcher.commands == [["check"]] * 3
    assert checks[0] == RepositoryCheck(ok=True)
    assert [check.ok for check in checks[1:]] == [False, False]
    assert "not referenced" in (checks[1].message or "")
    assert "already locked" in (checks[2].message or "")


def test_a_stopped_check_is_a_stop_not_a_failed_check() -> None:
    cancel = threading.Event()
    cancel.set()
    restic, launcher = _restic(Reply())

    with pytest.raises(ResticCancelledError):
        restic.check(cancel=cancel)

    assert launcher.launches == []


@pytest.mark.parametrize(
    ("paths", "ref"),
    [
        (("C:\\Users\\Admin\\workspace",), "a" * 64 + ":/C/Users/Admin/workspace"),
        (("/home/admin/workspace",), "a" * 64 + ":/home/admin/workspace"),
        (("/one", "/two"), "a" * 64),
    ],
    ids=["windows-folder", "posix-folder", "several-folders"],
)
def test_a_restore_writes_a_one_folder_snapshot_s_contents_and_never_overwrites(
    paths: tuple[str, ...], ref: str
) -> None:
    restic, launcher = _restic(Reply(stdout=[RESTORE_SUMMARY]))

    restic.restore(_snapshot(*paths), Path("/restored"))

    target = str(Path("/restored"))
    assert launcher.commands == [
        ["restore", ref, "--target", target, "--overwrite", "never", "--retry-lock", "1h"]
    ]


def test_a_restore_reports_its_figures_and_estimates_the_time_left() -> None:
    restic, _ = _restic(
        Reply(stdout=[RESTORE_STATUS, {"message_type": "verbose"}, RESTORE_SUMMARY])
    )
    heard: list[RestoreProgress] = []

    last = restic.restore(_snapshot("/workspace"), Path("/restored"), progress=heard.append)

    assert heard[0] == RestoreProgress(
        fraction=0.25,
        bytes_done=2_000_000,
        bytes_total=8_000_000,
        files_done=100,
        files_total=400,
        seconds_left=180,  # a quarter done in a minute leaves three
    )
    assert heard[1:] == [last]
    assert (last.fraction, last.files_done, last.seconds_left) == (1.0, 400, 0)


def test_a_restore_status_without_files_restored_keeps_none() -> None:
    """``--json`` leaves out fields that are zero."""
    restic, _ = _restic(Reply(stdout=[{"message_type": "status", "percent_done": 0.02}]))
    heard: list[RestoreProgress] = []

    restic.restore(_snapshot("/workspace"), Path("/restored"), progress=heard.append)

    assert (heard[0].fraction, heard[0].files_done, heard[0].seconds_left) == (0.02, None, None)


def test_the_password_is_verified_by_reading_the_config_without_a_lock() -> None:
    restic, launcher = _restic(
        Reply(stdout=[{"version": 2}]),
        Reply(exit_code=12, stderr=exit_error(12, "Fatal: wrong password or no key found")),
    )

    restic.verify_password()
    with pytest.raises(WrongPasswordError):
        restic.verify_password()

    assert launcher.commands == [["--no-lock", "cat", "config"]] * 2


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
