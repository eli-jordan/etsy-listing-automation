"""Read-only Etsy Open API v3 queries with the Naturally Inked Studio credentials.

Run from the repo root so the project's own transport handles the app key,
rate limits, retries and (with --auth) the rotating OAuth token:

    uv run python .claude/skills/etsy-api/etsy_api.py PATH [k=v ...] [--auth] [--all]

PATH is a v3 path such as /v3/application/listings/active. `{shop_id}` and
`{user_id}` in it are filled from the workspace. Query parameters are k=v;
repeat a key to send it more than once. Output is the JSON body on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from etsy_listings.core.clients.etsy.transport import Transport
from etsy_listings.core.connections import _etsy_app_key_source, etsy_token_store, etsy_transport
from etsy_listings.core.errors import UserFacingError

WORKSPACE = Path(
    os.environ.get(
        "ETSY_API_WORKSPACE", r"C:\Users\Admin\iCloudDrive\naturally-inked-studio-workspace"
    )
)
SHOP_ID = "67961328"
PAGE_LIMIT = 100


def _params(pairs: list[str]) -> list[tuple[str, str]]:
    out = []
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            sys.exit(f"query parameter must be k=v, got {pair!r}")
        out.append((key, value))
    return out


def _fill(path: str) -> str:
    path = path.replace("{shop_id}", SHOP_ID)
    if "{user_id}" in path:
        tokens = etsy_token_store(WORKSPACE).load()
        if tokens is None:
            sys.exit("no stored Etsy sign-in in the workspace; {user_id} needs one")
        path = path.replace("{user_id}", str(tokens.user_id))
    # Git Bash rewrites a leading-slash argument into a Windows path
    # (C:/Program Files/Git/v3/...), so locate the API path inside it.
    path = path.replace("\\", "/")
    if (at := path.find("v3/")) != -1:
        return "/" + path[at:]
    if (at := path.find("application/")) != -1:
        return "/v3/" + path[at:]
    return "/v3/application/" + path.lstrip("/")


def _get_all(transport: Transport, path: str, params: list[tuple[str, str]]) -> dict[str, Any]:
    """Follow limit/offset until `count` is reached."""
    base = [(k, v) for k, v in params if k not in ("limit", "offset")]
    results: list[Any] = []
    count = None
    while count is None or len(results) < count:
        page = [*base, ("limit", str(PAGE_LIMIT)), ("offset", str(len(results)))]
        body = transport.get(path, params=page).json()
        count = body.get("count", 0)
        batch = body.get("results", [])
        if not batch:
            break
        results.extend(batch)
    return {"count": count, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("path")
    parser.add_argument("params", nargs="*", help="query parameters as k=v")
    parser.add_argument(
        "--auth", action="store_true", help="send the shop owner's OAuth bearer (private shop data)"
    )
    parser.add_argument("--all", action="store_true", help="page through every result")
    args = parser.parse_args()

    if args.auth:
        transport = etsy_transport(WORKSPACE)
    else:
        transport = Transport(_etsy_app_key_source(WORKSPACE))

    path = _fill(args.path)
    params = _params(args.params)
    try:
        if args.all:
            body: Any = _get_all(transport, path, params)
        else:
            body = transport.get(path, params=params).json()
    except UserFacingError as error:
        sys.exit(f"{path}: {error}")
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        json.dump(body, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    except OSError:  # reader closed the pipe early (`| head`)
        pass


if __name__ == "__main__":
    main()
