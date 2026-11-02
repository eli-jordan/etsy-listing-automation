"""``ai/host.py``: the real machine behind every `CliHost` caller.

Everything else runs on `ScriptedCliHost`; this is where the production
adapter is shown to pass each question through to a real process.
"""

import shutil
import sys
from pathlib import Path

from etsy_listings.core.ai.host import LOCAL_CLI_HOST
from etsy_listings.core.ai.models import Deadline

_ECHO_UPPER = "import sys; sys.stdout.write(sys.stdin.read().upper()); sys.stderr.write('note')"


def test_which_is_shutils_lookup() -> None:
    assert LOCAL_CLI_HOST.which("python") == shutil.which("python")
    assert LOCAL_CLI_HOST.which("no-such-command-anywhere") is None


def test_run_captures_text_and_never_checks_the_exit_status() -> None:
    result = LOCAL_CLI_HOST.run(
        [sys.executable, "-c", _ECHO_UPPER + "; sys.exit(3)"], input_text="hi", timeout=30
    )
    assert (result.returncode, result.stdout, result.stderr) == (3, "HI", "note")


def test_run_can_leave_stderr_on_the_terminal_and_decode_as_asked() -> None:
    utf8 = "import sys; sys.stdin.reconfigure(encoding='utf-8'); "
    utf8 += "sys.stdout.reconfigure(encoding='utf-8'); "
    result = LOCAL_CLI_HOST.run(
        [sys.executable, "-c", utf8 + _ECHO_UPPER],
        input_text="é",
        capture_stderr=False,
        encoding="utf-8",
        timeout=30,
    )
    assert result.stdout == "É"
    assert result.stderr is None


def test_run_managed_is_the_process_owner(tmp_path: Path) -> None:
    result = LOCAL_CLI_HOST.run_managed(
        [sys.executable, "-c", _ECHO_UPPER],
        cwd=tmp_path,
        input_text="hi",
        deadline=Deadline.starting_now(seconds=30),
    )
    assert (result.returncode, result.stdout, result.timed_out) == (0, "HI", False)
