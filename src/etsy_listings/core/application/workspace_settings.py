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
from etsy_listings.core.workspace.yaml_source import ITSELF, UneditableYamlError, edit_yaml_bytes

CONCURRENCY = "batch_ai.concurrency"
WEIGHTS = "market_seo.weights"
PROVIDERS = "ai.providers"
STEP_LIMIT = "ai.step_limit_minutes"
RUN_LIMIT = "ai.run_limit_minutes"
TEMPLATE_POSITIONS = "template_positions"
BACKUP = "backup"
BACKUP_REPOSITORY = "backup.repository"
"""Not editable from Setup; written by the missing-repository actions."""
BACKUP_DESTINATIONS = "backup.destinations"
BACKUP_INTERVAL = "backup.interval_hours"
BACKUP_RETENTION = "backup.retention"
BACKUP_WORKSPACE_ID = "backup.workspace_id"
"""Not editable from Setup; written once, by ``backup_provisioning`` or
``backup_repository.ensure_workspace_id``."""
_WHOLE = 100
"""Percent: what the page's six shares total."""

EDITABLE_KEYS: tuple[str, ...] = (
    CONCURRENCY,
    WEIGHTS,
    PROVIDERS,
    STEP_LIMIT,
    RUN_LIMIT,
    TEMPLATE_POSITIONS,
    BACKUP_DESTINATIONS,
    BACKUP_INTERVAL,
    BACKUP_RETENTION,
)
"""One save may carry several keys. The page couples a provider enable or a
larger step limit with the run-limit increase it needs, so no written file
breaks ADR-0057's floor; nothing here raises the run limit on its own.

Backup's Setup page edits destinations, the interval and the retention; the
repository and the password are read-only there (interactions, *Set up and
Setup*), so only set-up writes the whole ``backup`` block, through
``backup_setup``. A destination is known by its path (``ITSELF``), so
removing one takes its comment with it and a kept one keeps its own."""


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
    path = workspace.settings_file()
    data, revision = read_revisioned(path, absent_ok=True)
    return SettingsView(revision, Settings.from_text(path, data.decode("utf-8-sig")))


def edit_settings(
    workspace: Workspace,
    *,
    expected_revision: str,
    changes: Mapping[str, object],
    editable: tuple[str, ...] = EDITABLE_KEYS,
) -> SettingsView:
    """Apply ``changes`` (dotted key to value) if ``settings.yaml`` is still
    at ``expected_revision``. ``editable`` widens what may change for an
    owner other than the Admin page, such as backup set-up.

    Refuses with :class:`SettingsRevisionConflictError` or
    :class:`InvalidSettingsEditError`, writing nothing either way.
    """
    _refuse_shape(changes, editable)
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


def check_settings_edit(
    workspace: Workspace,
    *,
    expected_revision: str,
    changes: Mapping[str, object],
    editable: tuple[str, ...] = EDITABLE_KEYS,
) -> None:
    """What :func:`edit_settings` would refuse for the same edit now,
    refused with the same errors, writing nothing: for an owner that saves
    only after a long step, such as backup provisioning's copy. The save
    still checks the revision again."""
    _refuse_shape(changes, editable)
    path = workspace.settings_file()
    source, revision = read_revisioned(path, absent_ok=True)
    if revision != expected_revision:
        raise SettingsRevisionConflictError
    _edited(path, source, changes)


def _refuse_shape(changes: Mapping[str, object], editable: tuple[str, ...]) -> None:
    refused = {key: "not editable from the Admin page" for key in changes if key not in editable}
    if WEIGHTS in changes and (problem := _percentage_problem(changes[WEIGHTS])):
        refused[WEIGHTS] = problem
    if TEMPLATE_POSITIONS in changes and not isinstance(changes[TEMPLATE_POSITIONS], Mapping):
        refused[TEMPLATE_POSITIONS] = "give the limits as scale, offset and rotation"
    if refused:
        raise InvalidSettingsEditError(refused)


def _edited(path: Path, source: bytes, changes: Mapping[str, object]) -> tuple[bytes, Settings]:
    raw = _document(path, source)
    original = _validated(raw)
    candidate: dict[str, Any] = copy.deepcopy(raw)
    for key, value in _leaf_changes(changes, original).items():
        node, leaf = parent_of(candidate, key)
        node[leaf] = copy.deepcopy(dict(value) if isinstance(value, Mapping) else value)
    validated = _validated(candidate)
    if PROVIDERS in changes:
        _retain_provider_source(raw, candidate, original, validated)
    try:
        edited = edit_yaml_bytes(source, candidate, sequence_keys=_SEQUENCE_KEYS)
    except UneditableYamlError as exc:
        raise InvalidSettingsEditError(
            {"__root__": f"{path}: {exc}. Edit this value in the file, then reload Settings."}
        ) from exc
    return edited, validated


_SEQUENCE_KEYS: dict[tuple[str, ...], str] = {
    ("ai", "providers"): "name",
    ("backup", "destinations"): ITSELF,
}


def _leaf_changes(changes: Mapping[str, object], original: Settings) -> dict[str, object]:
    """``changes`` with the limits section split into the leaves it changes.

    Every other key is written whole, as before. A leaf the file does not
    hold yet is unknown here and written, so validation can name it.
    """
    result = {key: value for key, value in changes.items() if key != TEMPLATE_POSITIONS}
    section = changes.get(TEMPLATE_POSITIONS)
    if isinstance(section, Mapping):
        current = original.template_positions.model_dump()
        result.update(
            (f"{TEMPLATE_POSITIONS}.{path}", value)
            for path, value in _leaves(section)
            if _at(current, path) != value
        )
    return result


def _leaves(mapping: Mapping[str, object], prefix: str = "") -> list[tuple[str, object]]:
    leaves: list[tuple[str, object]] = []
    for key, value in mapping.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            leaves += _leaves(value, f"{path}.")
        else:
            leaves.append((path, value))
    return leaves


_MISSING = object()


def _at(document: object, path: str) -> object:
    for part in path.split("."):
        if not isinstance(document, Mapping) or part not in document:
            return _MISSING
        document = document[part]
    return document


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
