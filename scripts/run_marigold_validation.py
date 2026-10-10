"""Supervise native release scripts, killing the owned process tree on timeout.

Run from the repository root with native Python. Pass source and new external
output directory. A failed stage stops the run and preserves prior measurements.
No installation, remote shop calls or input workspace changes occur.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run(source: Path, output: Path) -> None:
    commands = [
        ["scripts/validate_marigold.py", str(source), str(output)],
        ["scripts/validate_marigold_watchdog.py", str(output)],
        ["scripts/validate_marigold_shutdown.py", str(output)],
        ["scripts/validate_marigold_lifecycle.py", str(output)],
        ["scripts/validate_marigold_multiple.py", str(output)],
        ["scripts/validate_marigold_scenes.py", str(source), str(output)],
        ["scripts/review_marigold_validation.py", str(output)],
    ]
    for command in commands:
        process = subprocess.Popen([sys.executable, *command])
        try:
            code = process.wait(timeout=1800)
            if code:
                raise RuntimeError(f"Validation stage exited {code}: {command[0]}")
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"], timeout=30, check=False
                    )
                else:
                    process.kill()
                process.wait(timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
