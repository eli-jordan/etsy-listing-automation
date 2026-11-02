"""Public I/O contract using local executables, alongside real tree tests."""

import json
import os
import sys
from pathlib import Path

import pytest

from etsy_listings.core.ai.models import Deadline
from etsy_listings.core.ai.process import CliProcessError, run_managed


def test_run_managed_preserves_arguments_cwd_input_and_failure_output(tmp_path: Path):
    text = "prompt ✓ 日本語"
    script = (
        "import json,os,sys; "
        "print(json.dumps([os.getcwd(),sys.argv[1:],sys.stdin.read()])); "
        "sys.stderr.write('refused'); sys.exit(7)"
    )
    arguments = ["with spaces", 'quote"value', "trailing\\"]
    result = run_managed(
        [sys.executable, "-X", "utf8", "-c", script, *arguments],
        cwd=tmp_path,
        input_text=text,
        deadline=Deadline.starting_now(seconds=30),
    )
    cwd, args, received = json.loads(result.stdout)
    assert Path(cwd) == tmp_path
    assert args == arguments
    assert received == text
    assert result.stderr == "refused"
    assert result.returncode == 7
    assert not result.timed_out
    assert not result.cancelled


def test_run_managed_drains_large_streams_while_writing_input(tmp_path: Path):
    script = (
        "import sys; sys.stdout.write('o'*200000); sys.stdout.flush(); "
        "sys.stderr.write('e'*200000); sys.stderr.flush(); "
        "assert len(sys.stdin.read())==200000"
    )
    result = run_managed(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        input_text="i" * 200000,
        deadline=Deadline.starting_now(seconds=30),
    )
    assert result.returncode == 0
    assert result.stdout == "o" * 200000
    assert result.stderr == "e" * 200000
    assert not result.timed_out


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group delivery")
@pytest.mark.parametrize("refusal", [ProcessLookupError, PermissionError])
def test_run_managed_accepts_a_group_holding_only_its_exited_leader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: type[OSError]
):
    # Darwin's killpg skips zombies, so a completed command's group can report
    # no member while the leader is reserved but unreaped.
    def killpg_skipping_zombies(pgid: int, signum: int) -> None:
        raise refusal("no live member of the process group")

    monkeypatch.setattr(os, "killpg", killpg_skipping_zombies)
    result = run_managed(
        [sys.executable, "-c", "print('done')"],
        cwd=tmp_path,
        input_text="",
        deadline=Deadline.starting_now(seconds=30),
    )
    assert result.returncode == 0
    assert result.stdout == "done\n"


def test_run_managed_refuses_an_unlaunchable_executable(tmp_path: Path):
    with pytest.raises(CliProcessError, match="could not start and own"):
        run_managed(
            [str(tmp_path / "missing-executable")],
            cwd=tmp_path,
            input_text="",
            deadline=Deadline.starting_now(seconds=30),
        )


def test_run_managed_refuses_embedded_null_instead_of_truncating_arguments(tmp_path: Path):
    with pytest.raises(ValueError, match="null"):
        run_managed(
            [sys.executable, "-c", "print('correct')\x00truncated"],
            cwd=tmp_path,
            input_text="",
            deadline=Deadline.starting_now(seconds=30),
        )
