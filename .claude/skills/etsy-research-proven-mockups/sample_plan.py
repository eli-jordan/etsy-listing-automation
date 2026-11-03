"""Plan, pace and resume the search-page sampling for one proven-mockups run.

    uv run python sample_plan.py plan RUN_DIR "query" ...
    uv run python sample_plan.py next RUN_DIR
    uv run python sample_plan.py blocked RUN_DIR

`plan` writes RUN_DIR/plan.json: two pages per query (Star Seller, Bestseller,
newest first) and the file each page's extract is saved to. A page is done
once its file exists in RUN_DIR/pages/, so a run resumes wherever it stopped.

`next` prints the next pending page as JSON, with jittered waits to use before
loading it and after it loads (lists of seconds, each at most 10, the Chrome
tool's longest single wait), or {"done": true}.

`blocked` records that Etsy restricted access and prints when to retry:
roughly 15, 20, 30, then 45 minutes (each with jitter), climbing while no page
succeeds between blocks and starting over once one does. After a failed
45-minute retry it prints {"abort": true}.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

SEARCH = "https://www.etsy.com/search?q={q}&explicit=1&{flag}=true&order=date_desc"
FILTERS = (("star", "is_star_seller"), ("best", "is_best_seller"))
BETWEEN_PAGES = (20.0, 60.0)  # seconds before each page load
AFTER_LOAD = (3.0, 8.0)  # seconds for the page to settle before extracting
MAX_WAIT = 10.0  # longest single Chrome-tool wait
BACKOFF_MINUTES = (15, 20, 30, 45)
JITTER = (0.8, 1.15)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _waits(low: float, high: float) -> list[float]:
    total = random.uniform(low, high)
    chunks = []
    while total > 0:
        chunk = min(total, MAX_WAIT)
        chunks.append(round(chunk, 1))
        total -= chunk
    return chunks


def _load(run: Path, name: str) -> dict[str, Any]:
    path = run / name
    if not path.exists():
        sys.exit(f"{path} is missing; run `plan` first")
    return json.loads(path.read_text(encoding="utf-8"))


def _save(run: Path, name: str, data: dict[str, Any]) -> None:
    (run / name).write_text(json.dumps(data, indent=1), encoding="utf-8")


def _done(run: Path, plan: dict[str, Any]) -> int:
    return sum((run / "pages" / page["file"]).exists() for page in plan["pages"])


def plan(run: Path, queries: list[str]) -> None:
    (run / "pages").mkdir(parents=True, exist_ok=True)
    pages = []
    for i, query in enumerate(queries):
        for j, (tag, flag) in enumerate(FILTERS):
            number = 2 * i + j + 1
            pages.append(
                {
                    "file": f"{number:02d}-{_slug(query)}-{tag}.txt",
                    "url": SEARCH.format(q=quote_plus(query), flag=flag),
                }
            )
    _save(run, "plan.json", {"queries": queries, "pages": pages})
    _save(run, "state.json", {"step": -1, "done_at_block": -1})
    sys.stdout.write(f"{len(pages)} pages planned, {_done(run, {'pages': pages})} already done\n")


def next_page(run: Path) -> None:
    data = _load(run, "plan.json")
    pending = [p for p in data["pages"] if not (run / "pages" / p["file"]).exists()]
    if not pending:
        sys.stdout.write(json.dumps({"done": True}) + "\n")
        return
    page = pending[0]
    out = {
        "file": str(run / "pages" / page["file"]),
        "url": page["url"],
        "wait_before": _waits(*BETWEEN_PAGES),
        "wait_after_load": _waits(*AFTER_LOAD),
        "remaining": len(pending),
    }
    sys.stdout.write(json.dumps(out) + "\n")


def blocked(run: Path) -> None:
    data = _load(run, "plan.json")
    state = _load(run, "state.json")
    done = _done(run, data)
    step = 0 if done > state["done_at_block"] else state["step"] + 1
    _save(run, "state.json", {"step": step, "done_at_block": done})
    if step >= len(BACKOFF_MINUTES):
        sys.stdout.write(json.dumps({"abort": True, "pages_done": done}) + "\n")
        return
    minutes = BACKOFF_MINUTES[step] * random.uniform(*JITTER)
    run_at = datetime.now(UTC) + timedelta(minutes=minutes)
    out = {
        "retry": step + 1,
        "of": len(BACKOFF_MINUTES),
        "minutes": round(minutes, 1),
        "run_at": run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages_done": done,
    }
    sys.stdout.write(json.dumps(out) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("plan")
    make.add_argument("run", type=Path)
    make.add_argument("queries", nargs="+")
    sub.add_parser("next").add_argument("run", type=Path)
    sub.add_parser("blocked").add_argument("run", type=Path)
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.run, args.queries)
    elif args.command == "next":
        next_page(args.run)
    else:
        blocked(args.run)


if __name__ == "__main__":
    main()
