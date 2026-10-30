"""Edit a YAML document's values without rewriting the rest of it. ADR-0055.

Workspace YAML is seller-edited source: comments explain choices, key order
follows the seller's thinking, and the file may have CRLF line endings because
it was last saved on Windows. Dumping a changed mapping loses all of that, and
even a ruamel round-trip dump normalises indentation, quoting and line endings
the seller never touched. So an edit here is a set of splices into the original
text: ruamel's composer gives each node's exact span, the smallest node whose
value changed is re-rendered with ruamel at that spot, and every other byte is
copied through. A document whose values did not change comes back as the very
same string, so its owner writes nothing.

Values are compared and checked with PyYAML's ``safe_load``, the reader every
owner uses, and ruamel is held to the same YAML 1.1 rules so a rendered
``'yes'`` stays a string for that reader. After splicing, the result is read
back and must equal the intended document exactly. When it cannot -- an edit
through an alias, say -- :class:`UneditableYaml` is raised and the owner writes
nothing, rather than writing a file that means something else.

Owners do the reading, locking and atomic replacement; this module only turns
old text into new text. It never decides a path or creates a file.
"""

from __future__ import annotations

import codecs
import io
from collections.abc import Callable, Mapping
from typing import Any

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)

from etsy_listings.core.errors import UserFacingError

__all__ = ["UNSET", "UneditableYaml", "edit_yaml", "edit_yaml_bytes"]

UNSET: Any = object()
"""``before`` not given: the edit is two-way, against what the source reads as."""
_YAML_VERSION = (1, 1)
"""PyYAML's rules, which every reader of a workspace file applies."""


class UneditableYaml(UserFacingError, ValueError):
    """The edit cannot be made in place without changing what the file means,
    such as a value shared through a YAML alias. Nothing is written."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"cannot edit this YAML file in place: {detail}")


def edit_yaml_bytes(source: bytes, after: object, *, before: object = UNSET) -> bytes:
    """:func:`edit_yaml` over UTF-8 file bytes, keeping a byte-order mark.
    Returns ``source`` itself when nothing changes."""
    bom = codecs.BOM_UTF8 if source.startswith(codecs.BOM_UTF8) else b""
    text = source[len(bom) :].decode("utf-8")
    edited = edit_yaml(text, after, before=before)
    return source if edited is text else bom + edited.encode("utf-8")


def edit_yaml(source: str, after: object, *, before: object = UNSET) -> str:
    """``source`` changed so that it reads as ``after``, or ``source`` itself
    when it already does (key order is not a change).

    With ``before``, the edit is three-way: only the values that differ
    between ``before`` and ``after`` are applied to what ``source`` holds. An
    owner that writes a model dump passes the dump of the model it read, so
    defaults the seller never wrote stay unwritten and a ``25`` the model
    reads as ``"25.00"`` stays ``25``.
    """
    current = yaml.safe_load(source)
    wanted = _plain(after)
    target = wanted if before is UNSET else _merge(current, _plain(before), wanted)
    if _same(current, target):
        return source
    edited = _Editor(source).edit(current, target)
    if not _same(yaml.safe_load(edited), target):
        raise UneditableYaml("the edited text would not read back as the intended document")
    return edited


# ------------------------------------------------------------------ values


def _plain(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _same(a: object, b: object) -> bool:
    """Equal as a reader sees them: key order ignored, but ``1``, ``1.0`` and
    ``True`` are three different values in a file."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        assert isinstance(b, dict)
        return a.keys() == b.keys() and all(_same(a[key], b[key]) for key in a)
    if isinstance(a, list):
        assert isinstance(b, list)
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _merge(source: Any, before: Any, after: Any) -> Any:
    """``source`` with the changes from ``before`` to ``after`` applied."""
    if _same(before, after):
        return source
    if not (isinstance(source, dict) and isinstance(before, dict) and isinstance(after, dict)):
        return after
    result = {key: value for key, value in source.items() if key in after or key not in before}
    for key, value in after.items():
        if key in before and _same(before[key], value):
            continue
        if key in before and key in result:
            result[key] = _merge(result[key], before[key], value)
        else:
            result = _insert_after_predecessor(result, key, value, order=list(after))
    return result


def _insert_after_predecessor(
    mapping: dict[Any, Any], key: Any, value: Any, *, order: list[Any]
) -> dict[Any, Any]:
    """``mapping`` with ``key`` placed after the nearest key that precedes it
    in ``order`` and is already present, else last."""
    if key in mapping:
        mapping[key] = value
        return mapping
    preceding = [other for other in order[: order.index(key)] if other in mapping]
    if not preceding:
        return {**mapping, key: value}
    result: dict[Any, Any] = {}
    for existing, item in mapping.items():
        result[existing] = item
        if existing == preceding[-1]:
            result[key] = value
    return result


# ------------------------------------------------------------------ text


def _is_flow(node: Node) -> bool:
    return bool(getattr(node, "flow_style", False))


class _InPlaceRefused(Exception):
    """A collection cannot be edited line by line; replace it whole."""


Replace = Callable[[Any], None]


class _Editor:
    def __init__(self, source: str) -> None:
        self.source = source
        self.newline = "\r\n" if "\r\n" in source else "\n"
        composer = YAML(typ="rt", pure=True)
        composer.version = _YAML_VERSION
        try:
            self.root: Node | None = composer.compose(source)
        except Exception as exc:  # the reader already accepted it; ruamel must too
            raise UneditableYaml(str(exc)) from exc
        self.constructor = YAML(typ="safe", pure=True)
        self.constructor.version = _YAML_VERSION
        self.edits: list[tuple[int, int, int, str]] = []
        self.mapping_indent = 2
        self.sequence_offset = 0
        if self.root is not None:
            self._detect_indentation(self.root)

    def edit(self, current: Any, target: Any) -> str:
        if self.root is None:
            separator = "" if not self.source or self.source.endswith("\n") else self.newline
            body = self._lines(self._render(target), indent=0)
            return self.source + separator + body + self.newline
        self._edit(self.root, current, target, self._replace_root)
        return self._apply()

    def _apply(self) -> str:
        text = self.source
        # Highest start first; at one start, the longer span before inserts,
        # and later inserts before earlier so earlier ones end up first.
        for start, end, _, replacement in sorted(self.edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    def _splice(self, start: int, end: int, text: str) -> None:
        self.edits.append((start, end, len(self.edits), text.replace("\n", self.newline)))

    # -- walking

    def _edit(self, node: Node, old: Any, new: Any, replace: Replace) -> None:
        if _same(old, new):
            return
        try:
            if isinstance(node, MappingNode) and isinstance(old, dict) and isinstance(new, dict):
                if node.flow_style:
                    self._edit_flow_mapping(node, old, new)
                else:
                    self._edit_block_mapping(node, old, new)
                return
            if isinstance(node, SequenceNode) and isinstance(old, list) and isinstance(new, list):
                if node.flow_style:
                    self._edit_flow_sequence(node, old, new)
                else:
                    self._edit_block_sequence(node, old, new)
                return
        except _InPlaceRefused:
            pass
        if _is_flow(node) and isinstance(new, (dict, list)) and new:
            self._flow_replacer(node)(new)  # a flow collection stays one
        else:
            replace(self._styled(node, new))

    def _entries(self, node: MappingNode, old: dict[Any, Any]) -> list[tuple[Any, Node, Node]]:
        entries = []
        for key_node, value_node in node.value:
            key = self.constructor.constructor.construct_object(key_node, deep=True)
            if key not in old:
                raise UneditableYaml(f"key {key!r} does not read as written (a merge key?)")
            entries.append((key, key_node, value_node))
        return entries

    def _edit_flow_mapping(
        self, node: MappingNode, old: dict[Any, Any], new: dict[Any, Any]
    ) -> None:
        if old.keys() != new.keys():
            raise _InPlaceRefused
        for key, _, value_node in self._entries(node, old):
            self._edit(value_node, old[key], new[key], self._flow_replacer(value_node))

    def _edit_flow_sequence(self, node: SequenceNode, old: list[Any], new: list[Any]) -> None:
        if len(old) != len(new):
            raise _InPlaceRefused
        for item, before, after in zip(node.value, old, new, strict=True):
            self._edit(item, before, after, self._flow_replacer(item))

    def _edit_block_mapping(
        self, node: MappingNode, old: dict[Any, Any], new: dict[Any, Any]
    ) -> None:
        entries = self._entries(node, old)
        if not new or not entries:
            raise _InPlaceRefused
        column = entries[0][1].start_mark.column
        removed = [entry for entry in entries if entry[0] not in new]
        if any(not self._starts_its_line(key_node.start_mark.index) for _, key_node, _ in removed):
            raise _InPlaceRefused
        for key, key_node, value_node in entries:
            if key not in new:
                start = self._line_start(key_node.start_mark.index)
                self._splice(start, self._line_after(self._content_end(value_node)), "")
            else:
                self._edit(
                    value_node,
                    old[key],
                    new[key],
                    self._map_value_replacer(key_node, value_node, column),
                )
        ends = {key: self._content_end(value_node) for key, _, value_node in entries}
        order = list(new)
        for position, key in enumerate(order):
            if key in old:
                continue
            lines = self._render({key: new[key]}).split("\n")
            preceding = [other for other in order[:position] if other in old]
            if preceding:
                self._insert_lines_after(ends[preceding[-1]], lines, column)
            else:
                self._insert_lines_before(entries[0][1].start_mark.index, lines, column)

    def _edit_block_sequence(self, node: SequenceNode, old: list[Any], new: list[Any]) -> None:
        items: list[Node] = list(node.value)
        if not new or not items:
            raise _InPlaceRefused
        dashes = [self._dash(item) for item in items]
        column = dashes[0] - self._line_start(dashes[0])
        prefix = 0
        while prefix < min(len(old), len(new)) and _same(old[prefix], new[prefix]):
            prefix += 1
        suffix = 0
        while suffix < min(len(old), len(new)) - prefix and _same(
            old[-1 - suffix], new[-1 - suffix]
        ):
            suffix += 1
        changed_old = range(prefix, len(old) - suffix)
        changed_new = new[prefix : len(new) - suffix]
        paired = min(len(changed_old), len(changed_new))
        removed = list(changed_old)[paired:]
        if any(not self._starts_its_line(dashes[index]) for index in removed):
            raise _InPlaceRefused
        for offset in range(paired):
            index = prefix + offset
            self._edit(items[index], old[index], new[index], self._item_replacer(items[index]))
        for index in removed:
            start = self._line_start(dashes[index])
            self._splice(start, self._line_after(self._content_end(items[index])), "")
        added = changed_new[paired:]
        last_kept = prefix + paired - 1
        for value in added:
            lines = self._render_item(value).split("\n")
            if last_kept >= 0:
                self._insert_lines_after(self._content_end(items[last_kept]), lines, column)
            else:
                self._insert_lines_before(dashes[0], lines, column)

    # -- replacing one node

    def _replace_root(self, new: Any) -> None:
        assert self.root is not None
        rendered = self._lines(self._render(new), indent=0)
        self._splice(self.root.start_mark.index, self._content_end(self.root), rendered)

    def _flow_replacer(self, node: Node) -> Replace:
        def replace(new: Any) -> None:
            self._splice(node.start_mark.index, self._content_end(node), self._render_flow(new))

        return replace

    def _map_value_replacer(self, key_node: Node, value_node: Node, column: int) -> Replace:
        def replace(new: Any) -> None:
            rendered = self._lines(self._render({"k": new}), indent=column)
            remainder = rendered[len("k:") :]
            colon = self.source.index(":", key_node.end_mark.index)
            end = self._content_end(value_node)
            starts_later = "\n" in self.source[colon : value_node.start_mark.index]
            if (
                isinstance(value_node, ScalarNode)
                and value_node.style is None
                and not (value_node.value)
            ):  # an empty value: `key:` and nothing after it
                self._splice(colon + 1, colon + 1, remainder)
            elif starts_later and remainder.startswith("\n"):
                start = self._line_start(value_node.start_mark.index)
                self._splice(start, end, remainder[1:])
            elif starts_later:
                # The old block's last line goes whole, comment and all.
                line_end = self.source.find("\n", end)
                end = len(self.source) if line_end < 0 else line_end
                if self.source[end - 1 : end] == "\r":
                    end -= 1
                self._splice(colon + 1, end, remainder)
            elif remainder.startswith("\n"):
                self._splice(colon + 1, end, remainder)
            else:
                self._splice(value_node.start_mark.index, end, remainder.lstrip(" "))

        return replace

    def _item_replacer(self, item: Node) -> Replace:
        def replace(new: Any) -> None:
            dash = self._dash(item)
            rendered = self._lines(self._render_item(new), indent=dash - self._line_start(dash))
            self._splice(item.start_mark.index, self._content_end(item), rendered[2:])

        return replace

    def _insert_lines_after(self, end: int, lines: list[str], column: int) -> None:
        position = self._line_after(end)
        body = "\n".join(" " * column + line for line in lines)
        if position == len(self.source) and not self.source.endswith("\n"):
            self._splice(position, position, "\n" + body)
        else:
            self._splice(position, position, body + "\n")

    def _insert_lines_before(self, position: int, lines: list[str], column: int) -> None:
        indent = "\n" + " " * column
        self._splice(position, position, indent.join(lines) + indent)

    # -- rendering

    def _styled(self, node: Node, new: Any) -> Any:
        """``new`` in the old scalar's style, where that style can hold it."""
        if not isinstance(node, ScalarNode) or not isinstance(new, str):
            return new
        if node.style in ("|", ">") and "\n" in new.rstrip("\n") and not new.endswith("\n\n"):
            return LiteralScalarString(new)
        if node.style == "'" and "\n" not in new:
            return SingleQuotedScalarString(new)
        if node.style == '"' and "\n" not in new:
            return DoubleQuotedScalarString(new)
        return new

    def _dumper(self, *, flow: bool) -> YAML:
        dumper = YAML(typ="rt", pure=True)
        dumper.version = _YAML_VERSION
        dumper.width = 1_000_000
        dumper.allow_unicode = True
        dumper.indent(
            mapping=self.mapping_indent,
            sequence=self.sequence_offset + 2,
            offset=self.sequence_offset,
        )
        dumper.default_flow_style = flow
        dumper.representer.add_representer(
            type(None),
            lambda representer, _: representer.represent_scalar("tag:yaml.org,2002:null", "null"),
        )
        return dumper

    def _dump(self, value: Any, *, flow: bool) -> str:
        stream = io.StringIO()
        self._dumper(flow=flow).dump(value, stream)
        text = stream.getvalue()
        text = text.removeprefix("%YAML 1.1\n").removeprefix("---")
        text = text.removesuffix("\n").removesuffix("\n...")
        return text[1:] if text[:1] in (" ", "\n") else text

    def _render(self, value: Any) -> str:
        """Block style, at column 0, without a final newline."""
        return self._dump(value, flow=False)

    def _render_item(self, value: Any) -> str:
        """One block sequence item, its dash at column 0."""
        lines = self._render([value]).split("\n")
        return "\n".join(line[self.sequence_offset :] for line in lines)

    def _render_flow(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return self._dump(value, flow=True)
        return self._dump([value], flow=True)[1:-1]

    @staticmethod
    def _lines(text: str, *, indent: int) -> str:
        return text.replace("\n", "\n" + " " * indent)

    # -- positions

    def _content_end(self, node: Node) -> int:
        """Where the node's own text ends: before trailing blank lines and
        comments, which belong to whatever follows."""
        if isinstance(node, ScalarNode):
            if node.style in ("|", ">"):
                text = self.source[node.start_mark.index : node.end_mark.index]
                return int(node.start_mark.index) + len(text.rstrip(" \t\r\n"))
            return int(node.end_mark.index)
        if _is_flow(node) or not node.value:
            return int(node.end_mark.index)
        last = node.value[-1]
        return self._content_end(last[1] if isinstance(last, tuple) else last)

    def _line_start(self, index: int) -> int:
        return self.source.rfind("\n", 0, index) + 1

    def _line_after(self, index: int) -> int:
        newline = self.source.find("\n", index)
        return len(self.source) if newline < 0 else newline + 1

    def _starts_its_line(self, index: int) -> bool:
        return not self.source[self._line_start(index) : index].strip()

    def _dash(self, item: Node) -> int:
        index = int(item.start_mark.index) - 1
        while index >= 0 and self.source[index] in " \t\r\n":
            index -= 1
        if index < 0 or self.source[index] != "-":
            raise _InPlaceRefused
        return index

    def _detect_indentation(self, root: Node) -> None:
        """Match the file's own nesting for anything new: the first nested
        mapping gives the mapping indent, the first sequence under a key
        whether its dashes are indented."""
        found_mapping = found_sequence = False
        pending: list[Node] = [root]
        while pending and not (found_mapping and found_sequence):
            node = pending.pop(0)
            if not isinstance(node, MappingNode) or _is_flow(node):
                if isinstance(node, SequenceNode):
                    pending.extend(node.value)
                continue
            for key_node, value_node in node.value:
                pending.append(value_node)
                if (
                    isinstance(value_node, ScalarNode)
                    or _is_flow(value_node)
                    or not value_node.value
                ):
                    continue
                if isinstance(value_node, MappingNode) and not found_mapping:
                    indent = value_node.value[0][0].start_mark.column - key_node.start_mark.column
                    if indent > 0:
                        self.mapping_indent, found_mapping = indent, True
                if isinstance(value_node, SequenceNode) and not found_sequence:
                    try:
                        dash = self._dash(value_node.value[0])
                    except _InPlaceRefused:
                        continue
                    offset = dash - self._line_start(dash) - key_node.start_mark.column
                    if offset >= 0:
                        self.sequence_offset, found_sequence = offset, True
