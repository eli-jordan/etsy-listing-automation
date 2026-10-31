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
(ADR-0056). ``batch_ai.concurrency`` is read afresh by the
batch queue's next dispatch (ADR-0048), so a host wakes the queue after a
save. ``market_seo.weights`` arrives as the page shows it: whole
percentages for all six metrics totalling exactly 100. The file may still
hold relative weights written by hand; the page normalises those for
display only, and they are rewritten as percentages when the seller next
edits a share.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from etsy_listings.core.application.refusals import (
    InvalidSettingsEdit,
    SettingsRevisionConflict,
    field_errors_of,
)
from etsy_listings.core.config.errors import ConfigLoadError, parse_yaml
from etsy_listings.core.config.market_weights import METRICS, MarketWeights
from etsy_listings.core.config.settings import Settings
from etsy_listings.core.workspace.revisions import (
    RevisionConflict,
    read_revisioned,
    replace_if_unchanged,
)
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.core.workspace.yaml_source import edit_yaml_bytes

CONCURRENCY = "batch_ai.concurrency"
WEIGHTS = "market_seo.weights"
PROVIDERS = "ai.providers"

EDITABLE_KEYS: tuple[str, ...] = (CONCURRENCY, WEIGHTS, PROVIDERS)
"""Provider changes share the full-candidate save, so PR6 can couple an
enable with a run-limit increase in the same transaction (ADR-0057)."""


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

    Refuses with :class:`SettingsRevisionConflict` or
    :class:`InvalidSettingsEdit`, writing nothing either way.
    """
    refused = {
        key: "not editable from the Admin page" for key in changes if key not in EDITABLE_KEYS
    }
    if WEIGHTS in changes and (problem := _percentage_problem(changes[WEIGHTS])):
        refused[WEIGHTS] = problem
    if refused:
        raise InvalidSettingsEdit(refused)

    path = workspace.settings_file()
    adopted: list[Settings] = []

    def change(source: bytes) -> bytes:
        try:
            raw = parse_yaml(path, source.decode("utf-8-sig"))
        except ConfigLoadError as exc:
            raise InvalidSettingsEdit({"__root__": str(exc)}) from exc
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise InvalidSettingsEdit({"__root__": "settings.yaml is not a mapping"})
        # An invalid hand edit must be corrected in the file, never repaired
        # implicitly by a page patch (Admin plan, config-validation rule).
        try:
            original = Settings.model_validate(raw)
        except ValidationError as exc:
            raise InvalidSettingsEdit(field_errors_of(exc)) from exc
        candidate: dict[str, Any] = copy.deepcopy(raw)
        for key, value in changes.items():
            _assign(candidate, key.split("."), value)
        try:
            validated = Settings.model_validate(candidate)
            adopted.append(validated)
        except ValidationError as exc:
            raise InvalidSettingsEdit(field_errors_of(exc)) from exc
        if PROVIDERS in changes:
            _retain_provider_source(raw, candidate, original, validated)
        return edit_yaml_bytes(source, candidate, sequence_keys={("ai", "providers"): "name"})

    try:
        revised = replace_if_unchanged(path, expected_revision, change, absent_ok=True)
    except RevisionConflict as exc:
        raise SettingsRevisionConflict() from exc
    (settings,) = adopted
    return SettingsView(revised.revision, settings)


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
        if model.name not in source:
            continue
        for key in ("enabled", "model", "effort"):
            if getattr(models[model.name], key) != getattr(model, key):
                continue
            if key in source[model.name]:
                row[key] = source[model.name][key]
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
    if sum(values) != 100:
        return f"the shares total {sum(values)}%, not 100%"
    return None


def _assign(document: dict[str, Any], path: list[str], value: object) -> None:
    *parents, leaf = path
    node = document
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[leaf] = copy.deepcopy(dict(value) if isinstance(value, Mapping) else value)
