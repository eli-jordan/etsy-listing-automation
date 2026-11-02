"""The Admin page's Settings tab: ``settings.yaml`` read and edited.

Admin plan, PR 4, *Settings*. :func:`read_settings` and :func:`edit_settings`
follow ``shop_settings``' save rule with the file's own revision: the
candidate document is validated as a whole ``Settings`` before anything is
written, a stale revision is a conflict, and an edit that changes nothing
leaves the file byte-identical (``workspace.revisions``, ADR-0055).

``settings.yaml`` is optional. A missing file reads as every default at
``ABSENT_REVISION`` and the first save creates it holding only the edited
key. A file that does not load is refused naming the file and the dotted
key; nothing here repairs it or falls back to defaults.

``ai.providers`` captures order and per-provider preferences for future runs
(ADR-0056); ``ai.step_limit_minutes`` and ``ai.run_limit_minutes`` bound them
(ADR-0057). A running AI job keeps the configuration it captured at start.
``batch_ai.concurrency`` is read afresh by the batch queue's next dispatch
(ADR-0048), so a host wakes the queue after a save. ``market_seo.weights``
arrives as the page shows it: whole percentages for all six metrics
totalling exactly 100. The file may still hold relative weights written by
hand; the page normalises those for display only, and they are rewritten as
percentages when the seller next edits a share.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from etsy_listings.core.application.dotted_keys import parent_of
from etsy_listings.core.application.refusals import (
    InvalidSettingsEditError,
    SettingsRevisionConflictError,
    field_errors_of,
)
from etsy_listings.core.config.errors import ConfigLoadError, parse_yaml
from etsy_listings.core.config.market_weights import METRICS, MarketWeights
from etsy_listings.core.config.settings import Settings
from etsy_listings.core.workspace.revisions import (
    RevisionConflictError,
    read_revisioned,
    replace_if_unchanged,
)
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.core.workspace.yaml_source import UneditableYamlError, edit_yaml_bytes

CONCURRENCY = "batch_ai.concurrency"
WEIGHTS = "market_seo.weights"
PROVIDERS = "ai.providers"
STEP_LIMIT = "ai.step_limit_minutes"
RUN_LIMIT = "ai.run_limit_minutes"
_WHOLE = 100
"""Percent: what the page's six shares total."""

EDITABLE_KEYS: tuple[str, ...] = (CONCURRENCY, WEIGHTS, PROVIDERS, STEP_LIMIT, RUN_LIMIT)
"""One save may carry several keys. The page couples a provider enable or a
larger step limit with the run-limit increase it needs, so no written file
breaks ADR-0057's floor; nothing here raises the run limit on its own."""


@dataclass(frozen=True)
class SettingsView:
    revision: str
    """sha256 of ``settings.yaml``'s exact bytes, or ``ABSENT_REVISION``
    while there is no file; the next edit must name it."""
    settings: Settings


def default_weights() -> dict[str, int]:
    """``MarketWeights``' defaults as the page's percentages: what Reset
    writes. They already total 100; ``int`` only drops the float type."""
    defaults = MarketWeights()
    return {metric: int(defaults.of(metric)) for metric in METRICS}


def read_settings(workspace: Workspace) -> SettingsView:
    """``settings.yaml`` as it is now. A file that does not load raises
    ``ConfigLoadError`` naming it and the dotted key."""
    path = workspace.settings_file()
    data, revision = read_revisioned(path, absent_ok=True)
    return SettingsView(revision, Settings.from_text(path, data.decode("utf-8-sig")))


def edit_settings(
    workspace: Workspace, *, expected_revision: str, changes: Mapping[str, object]
) -> SettingsView:
    """Apply ``changes`` (dotted key to value) if ``settings.yaml`` is still
    at ``expected_revision``.

    Refuses with :class:`SettingsRevisionConflictError` or
    :class:`InvalidSettingsEditError`, writing nothing either way.
    """
    refused = {
        key: "not editable from the Admin page" for key in changes if key not in EDITABLE_KEYS
    }
    if WEIGHTS in changes and (problem := _percentage_problem(changes[WEIGHTS])):
        refused[WEIGHTS] = problem
    if refused:
        raise InvalidSettingsEditError(refused)

    path = workspace.settings_file()
    adopted: list[Settings] = []

    def change(source: bytes) -> bytes:
        edited, settings = _edited(path, source, changes)
        adopted.append(settings)
        return edited

    try:
        revised = replace_if_unchanged(path, expected_revision, change, absent_ok=True)
    except RevisionConflictError as exc:
        raise SettingsRevisionConflictError from exc
    (settings,) = adopted
    return SettingsView(revised.revision, settings)


def _edited(path: Path, source: bytes, changes: Mapping[str, object]) -> tuple[bytes, Settings]:
    """``source`` with ``changes`` applied, and the settings it then holds."""
    raw = _document(path, source)
    original = _validated(raw)
    candidate: dict[str, Any] = copy.deepcopy(raw)
    for key, value in changes.items():
        node, leaf = parent_of(candidate, key)
        node[leaf] = copy.deepcopy(dict(value) if isinstance(value, Mapping) else value)
    validated = _validated(candidate)
    if PROVIDERS in changes:
        _retain_provider_source(raw, candidate, original, validated)
    try:
        edited = edit_yaml_bytes(source, candidate, sequence_keys={("ai", "providers"): "name"})
    except UneditableYamlError as exc:
        raise InvalidSettingsEditError(
            {"__root__": f"{path}: {exc}. Edit this value in the file, then reload Settings."}
        ) from exc
    return edited, validated


def _retain_provider_source(
    raw: dict[str, Any], candidate: dict[str, Any], original: Settings, validated: Settings
) -> None:
    """The API materializes defaults for display. Unchanged preferences
    retain their original spelling and presence, even when rows move.
    Identity is the provider name, never its old position (ADR-0055/0056).
    """
    old_ai = raw.get("ai")
    if not isinstance(old_ai, dict) or not isinstance(old_ai.get("providers"), list):
        return
    source = {row["name"]: row for row in old_ai["providers"]}
    models = {row.name: row for row in original.ai.providers}
    for row, model in zip(candidate["ai"]["providers"], validated.ai.providers, strict=True):
        if model.name in source:
            _retain_row(row, source[model.name], before=models[model.name], after=model)


def _retain_row(
    row: dict[str, Any], source: dict[str, Any], *, before: object, after: object
) -> None:
    """``row`` with each unchanged preference spelled, or left out, as ``source`` had it."""
    for key in ("enabled", "model", "effort"):
        if getattr(before, key) != getattr(after, key):
            continue
        if key in source:
            row[key] = source[key]
        else:
            row.pop(key, None)


def _percentage_problem(weights: object) -> str | None:
    """Why ``weights`` is not the page's six whole percentages totalling 100.
    Negatives and an all-zero total are left to ``MarketWeights``, which
    names the metric, so a hand edit and a page edit read the same."""
    if not isinstance(weights, Mapping) or set(weights) != set(METRICS):
        return f"give a percentage for each of {', '.join(METRICS)}, and nothing else"
    values = list(weights.values())
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return "each share is a whole percentage"
    if sum(values) != _WHOLE:
        return f"the shares total {sum(values)}%, not 100%"
    return None


def _document(path: Path, source: bytes) -> dict[str, Any]:
    """``settings.yaml``'s mapping; an empty file is an empty one."""
    try:
        raw = parse_yaml(path, source.decode("utf-8-sig"))
    except ConfigLoadError as exc:
        raise InvalidSettingsEditError({"__root__": str(exc)}) from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InvalidSettingsEditError({"__root__": "settings.yaml is not a mapping"})
    return raw


def _validated(document: dict[str, Any]) -> Settings:
    """``document`` as ``Settings``, or refused naming each field. An invalid
    hand edit must be corrected in the file, never repaired implicitly by a
    page patch (Admin plan, config-validation rule)."""
    try:
        return Settings.model_validate(document)
    except ValidationError as exc:
        raise InvalidSettingsEditError(field_errors_of(exc)) from exc
