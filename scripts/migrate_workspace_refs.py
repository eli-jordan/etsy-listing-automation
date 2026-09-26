"""Rewrite a workspace's listing refs into PRD 72's two-root form.

    uv run python scripts/migrate_workspace_refs.py <workspace>           # dry run
    uv run python scripts/migrate_workspace_refs.py <workspace> --write   # apply

Every `listings/*/listing.yaml` used to write its paths relative to its own
directory, so a shared file read `../../designs/x.png`. PRD 72 gives a ref two
roots instead: no prefix is the workspace root, `./` is the listing's own
directory, and `..` is refused. This script is the one pass between the two.

It rewrites `design:` (a path or a map of them), `pricing_plan:` and every
file entry in `media:`, and nothing else. Each value is edited *in the text*,
at the span PyYAML's composer reports for it, rather than by loading and
dumping the document: PyYAML is the only YAML library here and a round trip
would drop every comment and re-quote every string. The edited text is then
re-parsed, checked to hold exactly the intended values, validated as a
`Listing` -- it must validate exactly as well as the original did, since a
listing already broken for another reason is reported, not this script's to
fix -- and each new ref is checked to resolve to the same file its old one
did. Only then is it written, atomically (`os.replace`).

Idempotent: a ref that does not start with `../` is already in the new form
and is left alone. Lockfiles are not touched -- the media stage keys Etsy ids
by ref, so shared images upload once more on the next `apply`, which is PRD
72's accepted cost.

A dry run is the default and prints every rewrite; nothing is written without
`--write`. A file that cannot be migrated is reported and left as it was; the
exit status is then 1.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from etsy_listings.config.defaults import Defaults
from etsy_listings.config.listing import Listing
from etsy_listings.workspace import layout, to_native_path
from etsy_listings.workspace.workspace import (
    InvalidRefError,
    PathEscapesWorkspaceError,
    Workspace,
)


class MigrationError(Exception):
    """One listing file this script will not rewrite, and why."""


@dataclass(frozen=True)
class Rewrite:
    where: str
    """`design`, `design.on-dark`, `pricing_plan`, `media[3]`."""
    line: int
    """1-based, as an editor shows it."""
    old: str
    new: str
    start: int
    end: int
    """The scalar's character span in the file, quotes included."""
    style: str | None
    """PyYAML's scalar style: None (plain), `'` or `"`."""


def new_ref(old: str, listing: str) -> str | None:
    """The two-root spelling of a listing-relative *old*, or None when *old*
    is not listing-relative (already migrated). Raises when it points outside
    the workspace -- there is no ref for that."""
    if not old.startswith("../"):
        return None
    listing_dir = f"{layout.LISTINGS_DIR}/{listing}"
    target = posixpath.normpath(posixpath.join(listing_dir, old))
    if target == ".." or target.startswith("../"):
        raise MigrationError(f"{old!r} points outside the workspace")
    if target.startswith(f"{listing_dir}/"):
        return f"./{target[len(listing_dir) + 1 :]}"
    return target


def _ref_nodes(root: yaml.Node) -> list[tuple[str, yaml.ScalarNode]]:
    """Every scalar node holding a path, with where it sits in the document."""
    if not isinstance(root, yaml.MappingNode):
        return []
    found: list[tuple[str, yaml.ScalarNode]] = []
    for key, value in root.value:
        name = key.value
        if name in ("design", "pricing_plan") and isinstance(value, yaml.ScalarNode):
            found.append((name, value))
        elif name == "design" and isinstance(value, yaml.MappingNode):
            found += [
                (f"design.{k.value}", v) for k, v in value.value if isinstance(v, yaml.ScalarNode)
            ]
        elif name == "media" and isinstance(value, yaml.SequenceNode):
            found += [
                (f"media[{i}]", item)
                for i, item in enumerate(value.value)
                if isinstance(item, yaml.ScalarNode)
            ]
    return found


def plan_rewrites(text: str, listing: str) -> list[Rewrite]:
    root = yaml.compose(text)
    rewrites: list[Rewrite] = []
    for where, node in [] if root is None else _ref_nodes(root):
        replacement = new_ref(node.value, listing)
        if replacement is None:
            continue
        if node.style not in (None, "'", '"'):
            raise MigrationError(f"{where}: a block scalar ref is not supported")
        rewrites.append(
            Rewrite(
                where=where,
                line=node.start_mark.line + 1,
                old=node.value,
                new=replacement,
                start=node.start_mark.index,
                end=node.end_mark.index,
                style=node.style,
            )
        )
    return rewrites


def _render(value: str, style: str | None) -> str:
    if style == "'":
        return "'" + value.replace("'", "''") + "'"
    if style == '"':
        # A JSON string is a valid YAML double-quoted scalar.
        return json.dumps(value, ensure_ascii=False)
    return value


def apply_rewrites(text: str, rewrites: list[Rewrite]) -> str:
    for rewrite in sorted(rewrites, key=lambda r: r.start, reverse=True):
        text = text[: rewrite.start] + _render(rewrite.new, rewrite.style) + text[rewrite.end :]
    return text


def _values(document: Any) -> dict[str, str]:
    """`where -> value` for every ref in a loaded document, for comparison."""
    values: dict[str, str] = {}
    if not isinstance(document, dict):
        return values
    design = document.get("design")
    if isinstance(design, str):
        values["design"] = design
    elif isinstance(design, dict):
        values |= {f"design.{k}": v for k, v in design.items() if isinstance(v, str)}
    if isinstance(document.get("pricing_plan"), str):
        values["pricing_plan"] = document["pricing_plan"]
    for i, item in enumerate(document.get("media") or []):
        if isinstance(item, str):
            values[f"media[{i}]"] = item
    return values


def _problems(workspace: Workspace, document: Any) -> list[tuple[Any, str]]:
    """What `Listing` validation says about *document*, comparably."""
    try:
        Listing.model_validate(document, context={"currency": workspace.defaults.etsy.currency})
    except ValidationError as exc:
        return [(error["loc"], error["msg"]) for error in exc.errors()]
    return []


def verify(
    workspace: Workspace, listing: str, before: str, after: str, rewrites: list[Rewrite]
) -> list[str]:
    """Prove *after* is *before* with exactly *rewrites* applied, validates
    exactly as well as *before* did, and names the same files.

    Answers what was already wrong with the listing before this script
    touched it: not this script's to fix, and no reason to leave its refs in
    a form nothing reads any more."""
    old_doc = yaml.safe_load(before)
    new_doc = yaml.safe_load(after)
    expected = _values(old_doc) | {r.where: r.new for r in rewrites}
    if _values(new_doc) != expected:
        raise MigrationError("the edited text did not re-parse to the intended refs")
    already = _problems(workspace, old_doc)
    if _problems(workspace, new_doc) != already:
        raise MigrationError("the edited listing no longer validates as it did")
    listing_dir = workspace.listing_dir(listing)
    for rewrite in rewrites:
        try:
            old_path = workspace.resolve(rewrite.old, relative_to=listing_dir)
            new_path = workspace.resolve_ref(rewrite.new, listing_dir=listing_dir)
        except (PathEscapesWorkspaceError, InvalidRefError) as exc:
            raise MigrationError(f"{rewrite.where}: {exc}") from exc
        if old_path != new_path:
            raise MigrationError(f"{rewrite.where}: {rewrite.new!r} names a different file")
    return [f"{'.'.join(str(part) for part in loc)}: {msg}" for loc, msg in already]


def _write_atomically(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".listing.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def migrate(root: Path, *, write: bool) -> int:
    workspace = Workspace(root=root.resolve(), defaults=Defaults.load(root / layout.SHOP_FILE))
    failed = 0
    changed = 0
    for listing in workspace.listing_names():
        path = workspace.listing_file(listing)
        if not path.is_file():
            continue
        shown = path.relative_to(workspace.root).as_posix()
        with path.open(encoding="utf-8", newline="") as handle:
            before = handle.read()
        try:
            rewrites = plan_rewrites(before, listing)
            if not rewrites:
                continue
            after = apply_rewrites(before, rewrites)
            already_invalid = verify(workspace, listing, before, after, rewrites)
        except (MigrationError, yaml.YAMLError) as exc:
            failed += 1
            print(f"{shown}: NOT MIGRATED -- {exc}")
            continue
        changed += 1
        print(shown)
        for r in rewrites:
            print(f"  {r.line}: {r.where}: {r.old} -> {r.new}")
        for problem in already_invalid:
            print(f"  note: already invalid before migrating, left as it is -- {problem}")
        if write:
            _write_atomically(path, after)
    if changed == 0 and failed == 0:
        print("nothing to migrate")
    elif changed and not write:
        print(f"dry run: {changed} file(s) would change; pass --write to apply")
    elif changed:
        print(f"wrote {changed} file(s); lockfiles untouched")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    # `str`, then translated: a cygwin path handed to native-Windows Python
    # must not reach pathlib first (AGENTS.md, `--root`).
    parser.add_argument("workspace", help="the workspace root (holds shop.yaml)")
    parser.add_argument("--write", action="store_true", help="apply; default is a dry run")
    args = parser.parse_args(argv)
    return migrate(to_native_path(args.workspace), write=args.write)


if __name__ == "__main__":
    sys.exit(main())
