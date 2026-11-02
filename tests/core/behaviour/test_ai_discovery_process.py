"""Discovery must bound real descendant-held pipes, including on Windows."""

import time
from pathlib import Path

from etsy_listings.core.ai.discovery import ModelDiscovery
from etsy_listings.core.ai.process import run_managed

from tests.support.ai_processes import local_cli
from tests.support.cli_host import ScriptedCliHost


def test_discovery_kills_descendants_and_returns_within_its_budget(tmp_path: Path) -> None:
    marker = tmp_path / "descendant.txt"
    descendant = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "end=time.monotonic()+8\n"
        "while time.monotonic()<end:\n"
        " with open(sys.argv[1], 'a') as f: f.write('x')\n"
        " time.sleep(0.02)\n"
    )
    parent = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable,'-c',{descendant!r},{str(marker)!r}])\n"
        "time.sleep(10)\n"
    )
    command = local_cli(tmp_path, parent)
    # The real process owner, behind a machine where only `codex` is installed.
    host = ScriptedCliHost(installed={"codex": str(command)}, managed={(): run_managed})
    started = time.monotonic()

    def clock():
        # Advance the budget only after the real descendant owns the pipe.
        # A slow CI interpreter start cannot race our timeout assertion.
        return time.monotonic() + (16 if marker.exists() else 0)

    result = ModelDiscovery(monotonic=clock, host=host).read()

    assert time.monotonic() - started < 6, "discovery waited for a descendant's natural exit"
    assert result.providers["codex"].problem
    assert marker.exists(), "the descendant never inherited the pipes"
    size = marker.stat().st_size
    time.sleep(0.3)
    assert marker.stat().st_size == size, "discovery left its descendant running"
