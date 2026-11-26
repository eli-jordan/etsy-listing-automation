"""What a local listing check reads off the workspace, read once per request.

* **Templates are gathered eagerly**, in ``gather``, because every check of
  every listing needs the whole map.
* **Garment profiles are read on demand and kept**, because a request usually
  wants one or two of them and a workspace may hold many.
* **Videos are probed on demand and kept, by file**: a shared clip in
  ``common-media/`` is named by many listings.

Two of those answers also outlive the request:

* **A template's entry is kept until a file in its directory changes**
  (:func:`~etsy_listings.core.workspace.file_version.tree_version`). Readiness
  is advisory here -- a listing issue -- and the render stage asks it again
  from the files before it acts.
* **A video's probe is kept until the file changes**
  (:func:`~etsy_listings.core.workspace.file_version.file_version`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path

from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.listing_validation import TemplateInfo
from etsy_listings.core.config.media import ProbeFailure, VideoFacts, media_kind
from etsy_listings.core.config.settings import Settings, SettingsProblem
from etsy_listings.core.render.config import (
    AnyTemplate,
    ColourMatrixTemplate,
    MultipleTemplate,
)
from etsy_listings.core.workspace.file_version import TreeVersion, file_version, tree_version
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.video import probe_video
from etsy_listings.core.workspace.workspace import InvalidNameError, InvalidRefError, Workspace

_TEMPLATE_INFO: BoundedCache[tuple[str, str, TreeVersion], tuple[TemplateInfo | None]] = (
    BoundedCache(256)
)
"""(workspace root, template, its directory's version) -> its entry, or
``None`` for one that will not load. Boxed in a tuple because the cache reads
a bare ``None`` as a miss."""

_PROBES: BoundedCache[tuple[str, tuple[int | str, ...]], VideoFacts | ProbeFailure] = BoundedCache(
    512
)
"""(path, file version) -> its probe."""


class WorkspaceFacts:
    def __init__(
        self,
        workspace: Workspace,
        *,
        garment_profile_names: tuple[str, ...],
        templates: Mapping[str, TemplateInfo],
    ) -> None:
        self._workspace = workspace
        self.garment_profile_names = garment_profile_names
        self.templates = templates
        self._profiles: dict[str, GarmentProfile | None] = {}
        self._probes: dict[Path, VideoFacts | ProbeFailure] = {}
        self._settings: Settings | SettingsProblem | None = None

    def settings(self) -> Settings | SettingsProblem:
        if self._settings is None:
            self._settings = self._workspace.settings_or_problem()
        return self._settings

    @classmethod
    def gather(cls, workspace: Workspace) -> WorkspaceFacts:
        return cls(
            workspace,
            garment_profile_names=tuple(workspace.garment_profile_names()),
            templates=_template_info_map(workspace),
        )

    @classmethod
    def for_files(cls, workspace: Workspace) -> WorkspaceFacts:
        return cls(workspace, garment_profile_names=(), templates={})

    def garment_profile(self, name: str) -> GarmentProfile | None:
        """``None`` for a profile that will not load *and* for a name that could
        never name a file at all -- ``""`` (a new listing, before the Variants
        dropdown has been touched) or anything that is not a single path
        segment.

        ``_segment``'s refusal is still the security boundary; all this decides
        is that an unusable value *stored in a listing* is a business issue
        (`_check_garment_profile_exists` reports it) rather than a 400 that
        takes the whole editor down with it.

        Note that this answering ``None`` and ``name`` being absent from
        :attr:`garment_profile_names` are *different* facts: a profile whose
        YAML is broken is listed but will not load. The existence check reads
        the names, so it stays quiet about it; the profile-dependent checks read
        this, so they skip. That is the behaviour this module inherited, and it
        is now at least visible in one place.
        """
        if name not in self._profiles:
            self._profiles[name] = self._load_garment_profile(name)
        return self._profiles[name]

    def videos(self, listing: Listing, listing_dir: Path) -> dict[str, VideoFacts | ProbeFailure]:
        result: dict[str, VideoFacts | ProbeFailure] = {}
        for entry in listing.media:
            if not isinstance(entry, str) or media_kind(entry) != "video":
                continue
            try:
                path = self._workspace.resolve_ref(entry, listing_dir=listing_dir)
            except InvalidRefError as exc:
                result[entry] = ProbeFailure(f"cannot be used: {exc.detail}")
                continue
            result[entry] = self.video(path)
        return result

    def video(self, path: Path) -> VideoFacts | ProbeFailure:
        if path not in self._probes:
            self._probes[path] = _remembered_probe(path)
        return self._probes[path]

    def _load_garment_profile(self, name: str) -> GarmentProfile | None:
        try:
            return self._workspace.load_garment_profile(name)
        except (ConfigLoadError, InvalidNameError):
            return None


def _template_info_map(workspace: Workspace) -> dict[str, TemplateInfo]:
    """Every *calibrated* template's real kind and colours, the way
    ``check_listing`` needs them -- an uncalibrated one has no kind to compare
    against and is silently skipped, the same as a template name that has
    since been renamed or deleted from under a listing."""
    result: dict[str, TemplateInfo] = {}
    root = str(workspace.root).casefold()
    for name in workspace.template_names():
        key = (root, name, tree_version(workspace.template_dir(name)))
        (info,) = _TEMPLATE_INFO.get_or_compute(key, partial(_read_template_info, workspace, name))
        if info is not None:
            result[name] = info
    return result


def _read_template_info(workspace: Workspace, name: str) -> tuple[TemplateInfo | None]:
    config = template_state(workspace, name).config
    if config is None:
        return (None,)
    info = template_info(workspace, name, config)
    from etsy_listings.core.preparation.readiness import (  # noqa: PLC0415 -- cycle: readiness imports core.workspace
        template_readiness,
    )

    maps = template_readiness(workspace, name, config)
    if not maps.can_render:
        info = replace(info, preparation_error=maps.message)
    return (info,)


def _remembered_probe(path: Path) -> VideoFacts | ProbeFailure:
    try:
        version = file_version(path)
    except OSError:
        return probe_video(path)
    return _PROBES.get_or_compute((str(path).casefold(), version), partial(probe_video, path))


def template_info(workspace: Workspace, name: str, config: AnyTemplate) -> TemplateInfo:
    if isinstance(config, ColourMatrixTemplate):
        colours = frozenset(workspace.template_colours(name))
    elif isinstance(config, MultipleTemplate):
        colours = frozenset(p.colour for p in config.placements if p.colour)
    else:
        colours = frozenset({config.colour}) if config.colour else frozenset()
    return TemplateInfo(kind=config.kind, colours=colours, config=config)
