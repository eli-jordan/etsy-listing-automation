"""A reader that stops early (``etsy-listings auth etsy --help | head``) ends
the command quietly rather than with a traceback.

Subject: ``cli.app.main``, the console-script entry point, run as a real
process so stdout is a real pipe whose read end closes.
"""

from __future__ import annotations

import subprocess
import sys


def test_a_closed_stdout_pipe_ends_the_command_without_a_traceback() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "from etsy_listings.cli.app import main; main()", "auth", "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    # The reader goes away before the command has printed anything, as
    # `head` does once it has its lines; every write after this fails.
    process.stdout.close()
    stderr = process.stderr.read()
    process.wait(timeout=120)

    assert b"Traceback" not in stderr
    assert b"Error" not in stderr
    assert process.returncode == 1
