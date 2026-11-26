"""Workspace root discovery and path resolution.

``Workspace.resolve()`` refuses to resolve outside the workspace root, a security
boundary the media and preview endpoints resolve through."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal, NamedTuple

import yaml
from pydantic import TypeAdapter

from etsy_listings.core.config.defaults import Defaults
from etsy_listings.core.config.description import DescriptionConfig, compose_description
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.exceptions import load_exceptions
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.media import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.config.settings import Settings, SettingsProblem
from etsy_listings.core.config.slug import ColourExceptions
from etsy_listings.core.render.config import AnyTemplate, PlacementId
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.atomic import read_bytes_retrying, write_yaml_atomic
from etsy_listings.core.workspace.common_copy import (
    CommonCopyDocument,
    CommonCopyError,
    parse_common_copy,
)
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.core.workspace.yaml_source import UNSET

logger = logging.getLogger(__name__)


class WorkspaceNotFoundError(FileNotFoundError):
    def __init__(self, start: Path) -> None:
        super().__init__(
            f"no '{layout.SHOP_FILE}' found in {start} or any parent directory; "
            f"pass --root, set {layout.ROOT_ENV_VAR}, or run from inside a workspace"
        )


class PathEscapesWorkspaceError(ValueError):
    def __init__(self, ref: str, root: Path) -> None:
        super().__init__(f"path {ref!r} escapes the workspace root ({root})")


class InvalidRefError(ConfigLoadError):
    def __init__(
        self, listing_dir: Path, ref: str, detail: str, *, file: str = layout.LISTING_FILE
    ) -> None:
        self.ref = ref
        self.detail = detail
        super().__init__(listing_dir / file, f"ref {ref!r}: {detail}")


@dataclass(frozen=True)
class DescriptionResolution:
    composed: str
    error: CommonCopyError | None = None


class InvalidNameError(ValueError):
    """Names arrive from URLs: this stops ``../../etc/passwd`` being joined
    onto the workspace root."""

    def __init__(self, name: str, message: str | None = None) -> None:
        super().__init__(message or f"{name!r} is not a valid name: expected a single path segment")


def _segment(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise InvalidNameError(name)
    return name


def _placement_segment(placement_id: str) -> str:
    return TypeAdapter(PlacementId).validate_python(placement_id)


class NotAMediaFileError(InvalidNameError):
    def __init__(self, path: str, directory: Path) -> None:
        super().__init__(path, f"{path!r} is not a media file in {directory.name}/")


_MEDIA_EXTENSIONS: tuple[str, ...] = (*IMAGE_EXTENSIONS, *VIDEO_EXTENSIONS)


def _is_media_file_in(path: Path, directory: Path) -> bool:
    """Judged on the resolved path too: a symlink inside the directory may
    point at another listing's files, or at ``shop.yaml`` behind a ``.png`` name."""
    if not path.is_file():
        return False
    target = path.resolve()
    if not target.is_relative_to(directory.resolve()):
        return False
    return path.suffix.lower() in _MEDIA_EXTENSIONS and target.suffix.lower() in _MEDIA_EXTENSIONS


class AmbiguousColourSuffixError(ValueError):
    def __init__(self, template: str, colour: str, candidates: list[Path]) -> None:
        names = ", ".join(sorted(p.name for p in candidates))
        super().__init__(
            f"template {template!r}: colour {colour!r} matches more than one photo by "
            f"filename suffix ({names}); rename the files so one matches exactly, or add "
            f"an exceptions.yaml entry"
        )


def _ends_with_colour_segments(stem: str, colour: str) -> bool:
    stem_segments = stem.split("-")
    colour_segments = colour.split("-")
    if len(colour_segments) > len(stem_segments):
        return False
    return stem_segments[len(stem_segments) - len(colour_segments) :] == colour_segments


def _looks_like_windows_absolute(ref: str) -> bool:
    """``PureWindowsPath("C:foo").is_absolute()`` is ``False`` (drive-relative),
    yet it leaves the workspace, as a UNC path does."""
    p = PureWindowsPath(ref)
    return p.drive != "" or ref.startswith(("\\\\", "//"))


_EXTENDED_LENGTH_PREFIX = "\\\\?\\"


def _without_extended_length_prefix(path: Path) -> Path:
    """``Path.resolve`` on Windows can keep the extended-length prefix (past
    MAX_PATH, or when another thread creates a directory between its two
    lookups), and the root resolved without it. UNC network paths keep theirs."""
    text = str(path)
    if text.startswith(_EXTENDED_LENGTH_PREFIX) and not text.startswith(
        _EXTENDED_LENGTH_PREFIX + "UNC\\"
    ):
        return Path(text[len(_EXTENDED_LENGTH_PREFIX) :])
    return path


_SCENE_STEM = "scene"
"""The fixed filename a ``multiple``/``single``-kind template's one photo
takes. Named once because two accessors turn on it: the scene image itself,
and :meth:`Workspace.template_photos`, which is everything *but* it."""


MaskSource = Literal["automatic", "edited", "metadata"]
"""Which of a placement's durable mask files: the generated baseline, the
seller's edited mask, or the metadata binding both to the main photo."""

_MASK_FILES: Mapping[MaskSource, str] = {
    "automatic": layout.AUTOMATIC_MASK_FILE,
    "edited": layout.EDITED_MASK_FILE,
    "metadata": layout.MASK_METADATA_FILE,
}


@dataclass(frozen=True)
class ScenePhoto:
    path: Path
    map_key: str


class TemplateCaches(NamedTuple):
    renders: Path
    previews: Path


class Workspace:
    def __init__(self, root: Path, defaults: Defaults) -> None:
        self.root = root
        self.defaults = defaults

    def snapshot(self) -> Workspace:
        return Workspace(self.root, self.defaults)

    def browser_storage_id(self) -> str:
        native_root = os.path.normcase(str(self.root.resolve()))
        return hashlib.sha256(native_root.encode("utf-8")).hexdigest()

    @classmethod
    def discover(
        cls,
        start: Path | None = None,
        *,
        root_override: Path | None = None,
    ) -> Workspace:
        root = cls._find_root(start=start, root_override=root_override)
        defaults = Defaults.load(root / layout.SHOP_FILE)
        return cls(root=root, defaults=defaults)

    @staticmethod
    def _find_root(*, start: Path | None, root_override: Path | None) -> Path:
        if root_override is not None:
            candidate = root_override.resolve()
            if not (candidate / layout.SHOP_FILE).is_file():
                raise WorkspaceNotFoundError(candidate)
            return candidate

        # A raw string, so it may still be in Cygwin form.
        env_root = os.environ.get(layout.ROOT_ENV_VAR)
        if env_root:
            candidate = to_native_path(env_root).resolve()
            if not (candidate / layout.SHOP_FILE).is_file():
                raise WorkspaceNotFoundError(candidate)
            return candidate

        search_start = (start or Path.cwd()).resolve()
        for candidate in (search_start, *search_start.parents):
            if (candidate / layout.SHOP_FILE).is_file():
                return candidate
        raise WorkspaceNotFoundError(search_start)

    def resolve(self, ref: str, relative_to: Path) -> Path:
        """The escape check every path goes through."""
        if Path(ref).is_absolute() or _looks_like_windows_absolute(ref):
            raise PathEscapesWorkspaceError(ref, self.root)

        candidate = _without_extended_length_prefix((relative_to / ref).resolve())
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PathEscapesWorkspaceError(ref, self.root) from exc
        return candidate

    def resolve_ref(self, ref: str, *, listing_dir: Path) -> Path:
        """The one interpreter of a path written in ``listing.yaml``.

        ``listing_dir`` rather than a name, because the editor's unnamed draft
        has no directory of its own and resolves against a stand-in at the
        same depth.
        """
        return self._resolve_owned_ref(ref, listing_dir, layout.LISTING_FILE)

    def resolve_template_ref(self, ref: str, *, template: str) -> Path:
        return self._resolve_owned_ref(
            ref, self.listing_template_dir(template), layout.TEMPLATE_FILE
        )

    def _resolve_owned_ref(self, ref: str, owner_dir: Path, owner_file: str) -> Path:
        def refused(detail: str) -> InvalidRefError:
            return InvalidRefError(owner_dir, ref, detail, file=owner_file)

        if Path(ref).is_absolute() or _looks_like_windows_absolute(ref):
            raise refused("an absolute path is not a ref")
        if "\\" in ref:
            raise refused("use '/' between directories, not a backslash")
        if ".." in ref.split("/"):
            raise refused("'..' is not allowed in a ref")
        base, rest = (owner_dir, ref[2:]) if ref.startswith("./") else (self.root, ref)
        if all(segment in ("", ".") for segment in rest.split("/")):
            raise refused("the ref is empty")
        try:
            return self.resolve(rest, relative_to=base)
        except PathEscapesWorkspaceError as exc:
            raise refused(str(exc)) from exc

    def cache(self, *parts: str) -> Path:
        return self.root.joinpath(layout.CACHE_DIR, *parts)

    def listing_names(self) -> list[str]:
        listings = self.root / layout.LISTINGS_DIR
        if not listings.is_dir():
            return []
        names: list[str] = []
        for path in listings.iterdir():
            if not path.is_dir():
                continue
            if (path / layout.LISTING_FILE).is_file() or (path / layout.LOCK_FILE).is_file():
                names.append(path.name)
        return sorted(names)

    def listing_directory_names(self) -> list[str]:
        listings = self.root / layout.LISTINGS_DIR
        if not listings.is_dir():
            return []
        return sorted(path.name for path in listings.iterdir() if path.is_dir())

    def listing_dir(self, listing: str) -> Path:
        return self.root / layout.LISTINGS_DIR / _segment(listing)

    def draft_listing_dir(self) -> Path:
        return self.root / layout.LISTINGS_DIR / "_"

    def listing_file(self, listing: str) -> Path:
        return self.listing_dir(listing) / layout.LISTING_FILE

    def listing_templates_dir(self) -> Path:
        return self.root / layout.LISTING_TEMPLATES_DIR

    def listing_template_names(self) -> list[str]:
        directory = self.listing_templates_dir()
        if not directory.is_dir():
            return []
        return sorted(
            path.name
            for path in directory.iterdir()
            if path.is_dir() and (path / layout.TEMPLATE_FILE).is_file()
        )

    def listing_template_dir(self, template: str) -> Path:
        return self.listing_templates_dir() / _segment(template)

    def listing_template_file(self, template: str) -> Path:
        return self.listing_template_dir(template) / layout.TEMPLATE_FILE

    def listing_template_assets_dir(self, template: str) -> Path:
        return self.listing_template_dir(template) / layout.LISTING_TEMPLATE_ASSETS_DIR

    def listing_template_media_file(self, template: str, path: str) -> Path:
        return self._media_file_in(self.listing_template_dir(template), path)

    def listing_template_media_files(self, template: str) -> list[Path]:
        return self._media_files_in(self.listing_template_assets_dir(template))

    def remove_listing_template(self, template: str) -> None:
        directory = self.listing_template_dir(template)
        if directory.is_dir():
            remove_tree(directory)

    def load_listing_template(self, template: str) -> ListingTemplate:
        return ListingTemplate.load(
            self.listing_template_file(template),
            currency=self.defaults.etsy.currency,
            read=read_bytes_retrying,
        )

    def write_listing_template(self, template: str, document: ListingTemplate) -> None:
        path = self.listing_template_file(template)
        dumped = document.model_dump(mode="json", exclude_defaults=True)
        before: object = UNSET
        try:
            current = self.load_listing_template(template)
        except ConfigLoadError:
            pass
        else:
            before = current.model_dump(mode="json", exclude_defaults=True)
        write_yaml_atomic(
            path,
            dumped,
            before=before,
            new=lambda: yaml.safe_dump(dumped, sort_keys=False, allow_unicode=True),
        )

    def resolve_frozen_template_ref(self, ref: str, *, frozen_dir: Path) -> Path:
        return self._resolve_owned_ref(ref, frozen_dir, layout.TEMPLATE_FILE)

    # Batch creation's cache records: ids come from URLs, so each one is a `_segment`.

    def staging_ids(self) -> list[str]:
        return self._cache_entries(layout.STAGING_DIR, directories=True)

    def staging_dir(self, session: str) -> Path:
        return self.cache(layout.STAGING_DIR, _segment(session))

    def staging_session_file(self, session: str) -> Path:
        return self.staging_dir(session) / layout.STAGING_SESSION_FILE

    def staging_upload_file(self, session: str, sha256: str) -> Path:
        return self.staging_dir(session) / layout.STAGING_UPLOADS_DIR / f"{_segment(sha256)}.png"

    def staging_archive_file(self, session: str) -> Path:
        return self.staging_dir(session) / layout.STAGING_ARCHIVE_FILE

    def staging_template_dir(self, session: str) -> Path:
        return self.staging_dir(session) / layout.FROZEN_TEMPLATE_DIR

    def batch_ids(self) -> list[str]:
        return self._cache_entries(layout.BATCHES_DIR, directories=False)

    def batch_file(self, batch: str) -> Path:
        return self.cache(layout.BATCHES_DIR, f"{_segment(batch)}.json")

    def batch_dir(self, batch: str) -> Path:
        return self.cache(layout.BATCHES_DIR, _segment(batch))

    def batch_template_dir(self, batch: str) -> Path:
        return self.batch_dir(batch) / layout.FROZEN_TEMPLATE_DIR

    def batch_upload_file(self, batch: str, sha256: str) -> Path:
        return self.batch_dir(batch) / layout.STAGING_UPLOADS_DIR / f"{_segment(sha256)}.png"

    def _cache_entries(self, directory: str, *, directories: bool) -> list[str]:
        parent = self.cache(directory)
        if not parent.is_dir():
            return []
        if directories:
            return sorted(p.name for p in parent.iterdir() if p.is_dir())
        return sorted(p.stem for p in parent.glob("*.json") if p.is_file())

    def preparation_jobs(self) -> list[str]:
        return self._cache_entries("preparation/jobs", directories=False)

    def preparation_job_file(self, job: str) -> Path:
        return self.cache("preparation", "jobs", _segment(job) + ".json")

    def preparation_work(self, job: str, file: str | None = None) -> Path:
        directory = self.cache("preparation", "work", _segment(job))
        return directory if file is None else directory / _segment(file)

    def preparation_predictions_dir(self, template: str) -> Path:
        return self.cache("preparation", "predictions", _segment(template))

    def preparation_prediction_current(self, template: str) -> Path:
        return self.cache("preparation", "predictions", _segment(template), "current.json")

    def preparation_prediction_set(self, template: str, identity: str) -> Path:
        return self.cache(
            "preparation", "predictions", _segment(template), "sets", _segment(identity)
        )

    def preparation_prediction_sets(self, template: str) -> list[str]:
        directory = self.cache("preparation", "predictions", _segment(template), "sets")
        return (
            sorted(p.name for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []
        )

    def preparation_work_ids(self) -> list[str]:
        return self._cache_entries("preparation/work", directories=True)

    def remove_preparation_work(self, job: str) -> None:
        remove_tree(self.preparation_work(job))

    def remove_prediction_set(self, template: str, identity: str) -> None:
        remove_tree(self.preparation_prediction_set(template, identity))

    def position_fit(self, key: str) -> Path:
        return self.cache("position-fits", _segment(key))

    def position_fits(self) -> list[str]:
        return self._cache_entries("position-fits", directories=True)

    def remove_position_fit(self, key: str) -> None:
        remove_tree(self.position_fit(key))

    def design_ref(self, design: str) -> str:
        return f"{layout.DESIGNS_DIR}/{_segment(design)}.png"

    def design_content_hash(
        self, design: Mapping[str, str | None], *, listing_dir: Path
    ) -> str | None:
        """No absolute path enters the hash, and ``null`` slots do: an emptied
        slot is a different listing to review."""
        if not design:
            return None
        digest = hashlib.sha256()
        for key, ref in sorted(design.items()):
            content_hash = None if ref is None else self._readable_hash(ref, listing_dir)
            entry = json.dumps((key, ref, content_hash), ensure_ascii=False)
            digest.update(entry.encode("utf-8"))
        return digest.hexdigest()

    def _readable_hash(self, ref: str, listing_dir: Path) -> str | None:
        try:
            path = self.resolve_ref(ref, listing_dir=listing_dir)
            file_digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    file_digest.update(chunk)
        except (OSError, InvalidRefError):
            return None
        return file_digest.hexdigest()

    def lock_file(self, listing: str) -> Path:
        return self.listing_dir(listing) / layout.LOCK_FILE

    def designs_dir(self) -> Path:
        return self.root / layout.DESIGNS_DIR

    def design_file(self, design: str) -> Path:
        return self.designs_dir() / f"{_segment(design)}.png"

    def design_files(self) -> list[Path]:
        designs = self.designs_dir()
        if not designs.is_dir():
            return []
        return sorted(p for p in designs.glob("*.png") if p.is_file())

    def common_media_dir(self) -> Path:
        return self.root / layout.COMMON_MEDIA_DIR

    def common_media_file(self, path: str) -> Path:
        return self._media_file_in(self.common_media_dir(), path)

    def common_media_files(self) -> list[Path]:
        return self._media_files_in(self.common_media_dir())

    def listing_media_file(self, listing: str, path: str) -> Path:
        return self._media_file_in(self.listing_dir(listing), path)

    def listing_media_files(self, listing: str) -> list[Path]:
        return self._media_files_in(self.listing_dir(listing))

    def _media_file_in(self, directory: Path, path: str) -> Path:
        """Tighter than :meth:`resolve`: the file must resolve inside
        ``directory``, not merely the root. A missing file is the caller's 404."""
        joined = "/".join(_segment(segment) for segment in path.split("/"))
        if Path(joined).suffix.lower() not in _MEDIA_EXTENSIONS:
            raise NotAMediaFileError(path, directory)
        try:
            candidate = self.resolve(joined, relative_to=directory)
        except PathEscapesWorkspaceError as exc:
            raise NotAMediaFileError(path, directory) from exc
        if not candidate.is_relative_to(directory.resolve()):
            raise NotAMediaFileError(path, directory)
        if candidate.suffix.lower() not in _MEDIA_EXTENSIONS:
            raise NotAMediaFileError(path, directory)
        return candidate

    def _media_files_in(self, directory: Path) -> list[Path]:
        if not directory.is_dir():
            return []
        return sorted(
            (p for p in directory.rglob("*") if _is_media_file_in(p, directory)),
            key=lambda p: p.relative_to(directory).as_posix(),
        )

    def seo_prompt_file(self) -> Path:
        return self.root / layout.PROMPTS_DIR / layout.SEO_PROMPT_FILE

    def brief_prompt_file(self) -> Path:
        return self.root / layout.PROMPTS_DIR / layout.BRIEF_PROMPT_FILE

    def market_queries_prompt_file(self) -> Path:
        return self.root / layout.PROMPTS_DIR / layout.MARKET_QUERIES_PROMPT_FILE

    def common_copy_dir(self) -> Path:
        return self.root / layout.COMMON_COPY_DIR

    def common_copy_file(self, ref: str) -> Path:
        """Narrower than :meth:`resolve_ref`: the result must land inside
        ``common-copy/``, so ``common-copy/../listings/x`` is refused too."""
        prefix = f"{layout.COMMON_COPY_DIR}/"
        if not ref.startswith(prefix):
            raise PathEscapesWorkspaceError(ref, self.root)
        candidate = self.resolve(ref, relative_to=self.root)
        try:
            candidate.relative_to(self.common_copy_dir())
        except ValueError as exc:
            raise PathEscapesWorkspaceError(ref, self.root) from exc
        return candidate

    def common_copy_files(self) -> list[Path]:
        shared = self.common_copy_dir()
        if not shared.is_dir():
            return []
        return sorted(p for p in shared.glob("*.md") if p.is_file())

    def load_common_copy(self, ref: str) -> CommonCopyDocument:
        path = self.common_copy_file(ref)
        if not path.is_file():
            raise CommonCopyError(f"{ref!r}: file not found")
        return parse_common_copy(ref, path.read_text(encoding="utf-8"))

    def resolve_description(self, description: DescriptionConfig) -> DescriptionResolution:
        text = description.text
        if description.ref is not None:
            try:
                text = self.load_common_copy(description.ref).body
            except CommonCopyError as exc:
                return DescriptionResolution(compose_description(description.lead, None), exc)
        return DescriptionResolution(compose_description(description.lead, text))

    def compose_description(self, description: DescriptionConfig) -> str:
        resolved = self.resolve_description(description)
        if resolved.error is not None:
            raise resolved.error
        return resolved.composed

    def garment_profile_names(self) -> list[str]:
        garment_profiles = self.root / layout.GARMENT_PROFILES_DIR
        if not garment_profiles.is_dir():
            return []
        return sorted(p.stem for p in garment_profiles.glob("*.yaml") if p.is_file())

    def garment_profile_file(self, garment_profile: str) -> Path:
        return self.root / layout.GARMENT_PROFILES_DIR / f"{_segment(garment_profile)}.yaml"

    def pricing_plans_dir(self) -> Path:
        return self.root / layout.PRICING_PLANS_DIR

    def pricing_plan_files(self) -> list[Path]:
        root = self.pricing_plans_dir()
        if not root.is_dir():
            return []
        return sorted(p for p in root.rglob("*.yaml") if p.is_file())

    def settings_file(self) -> Path:
        return self.root / layout.SETTINGS_FILE

    def exceptions_file(self) -> Path:
        return self.root / layout.EXCEPTIONS_FILE

    def templates_dir(self) -> Path:
        return self.root / layout.MOCKUP_TEMPLATES_DIR

    def template_names(self, *, include_uncalibrated: bool = False) -> list[str]:
        templates = self.templates_dir()
        if not templates.is_dir():
            return []
        return sorted(
            p.name
            for p in templates.iterdir()
            if p.is_dir() and (include_uncalibrated or (p / layout.TEMPLATE_FILE).is_file())
        )

    def template_dir(self, template: str) -> Path:
        return self.templates_dir() / _segment(template)

    def has_template(self, template: str) -> bool:
        return self.template_dir(template).is_dir()

    def template_photos(self, template: str) -> list[Path]:
        directory = self.template_dir(template)
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.glob("*.png") if p.stem != _SCENE_STEM)

    def template_colours(self, template: str) -> list[str]:
        return [photo.stem for photo in self.template_photos(template)]

    def template_preview_photo(self, template: str) -> Path | None:
        scene = self.template_scene_image(template)
        if scene.is_file():
            return scene
        return next(iter(self.template_photos(template)), None)

    def template_config_file(self, template: str) -> Path:
        return self.template_dir(template) / layout.TEMPLATE_FILE

    def template_main_photo(self, template: str, config: AnyTemplate) -> Path:
        """ADR-0054: ordinal first actual colour photo; fixed kinds use scene."""
        if config.kind == "colour-matrix":
            photos = sorted(self.template_photos(template), key=lambda photo: photo.name)
            if not photos:
                raise FileNotFoundError(f"No main photo for template {template!r}")
            return photos[0]
        return self.template_scene_image(template)

    def template_renderer_dir(self, template: str) -> Path:
        return self.template_dir(template) / layout.RENDERER_DIR

    def template_renderer_settings_file(self, template: str) -> Path:
        return self.template_renderer_dir(template) / layout.RENDERER_SETTINGS_FILE

    def template_calibration_transaction(self, template: str) -> Path:
        return self.template_renderer_dir(template) / layout.CALIBRATION_TRANSACTION_DIR

    def template_calibration_receipt(self, template: str) -> Path:
        return self.template_renderer_dir(template) / layout.CALIBRATION_RECEIPT_FILE

    def template_mask_dir(self, template: str, placement_id: str | None = None) -> Path:
        directory = self.template_renderer_dir(template) / layout.MASKS_DIR
        if placement_id is not None:
            directory /= _placement_segment(placement_id)
        return self.resolve(directory.relative_to(self.root).as_posix(), self.root)

    def template_mask_file(
        self, template: str, placement_id: str | None = None, *, source: MaskSource = "edited"
    ) -> Path:
        return self.template_mask_dir(template, placement_id) / _MASK_FILES[source]

    def template_brush_history(self, template: str, placement_id: str | None = None) -> Path:
        stem = _placement_segment(placement_id) if placement_id is not None else "implicit"
        directory = self.cache(layout.PREPARATION_DIR, layout.BRUSHES_DIR, _segment(template))
        return directory / f"{stem}.json"

    def template_maps_dir(self, template: str) -> Path:
        directory = self.template_renderer_dir(template) / layout.MAPS_DIR
        return self.resolve(directory.relative_to(self.root).as_posix(), self.root)

    def template_map_current(self, template: str) -> Path:
        return self.template_maps_dir(template) / layout.MAP_CURRENT_FILE

    def template_map_generation_dir(
        self, template: str, generation: str, *, staging: bool = False
    ) -> Path:
        directory = (
            self.template_maps_dir(template)
            / (layout.MAP_STAGING_DIR if staging else layout.MAP_GENERATIONS_DIR)
            / _segment(generation)
        )
        return self.resolve(directory.relative_to(self.root).as_posix(), self.root)

    def template_map_manifest(
        self, template: str, generation: str, *, staging: bool = False
    ) -> Path:
        return (
            self.template_map_generation_dir(template, generation, staging=staging)
            / layout.MAP_MANIFEST_FILE
        )

    def template_map_file(
        self, template: str, generation: str, placement_id: str | None, *, staging: bool = False
    ) -> Path:
        # Explicit IDs may be named "placement"; implicit and explicit sets never mix.
        filename = f"{_segment(placement_id) if placement_id is not None else 'placement'}.npz"
        path = self.template_map_generation_dir(template, generation, staging=staging) / filename
        return self.resolve(path.relative_to(self.root).as_posix(), self.root)

    def template_map_generations(self, template: str, *, staging: bool = False) -> list[str]:
        directory = self.template_maps_dir(template) / (
            layout.MAP_STAGING_DIR if staging else layout.MAP_GENERATIONS_DIR
        )
        directory = self.resolve(directory.relative_to(self.root).as_posix(), self.root)
        if not directory.exists():
            return []
        return sorted(path.name for path in directory.iterdir() if path.is_dir())

    def remove_map_generation(
        self, template: str, generation: str, *, staging: bool = False
    ) -> None:
        remove_tree(self.template_map_generation_dir(template, generation, staging=staging))

    def template_derived_dir(self, template: str) -> Path:
        return self.template_renderer_dir(template) / layout.DERIVED_DIR

    def template_base_image(self, template: str, colour: str) -> Path:
        exact = self.template_dir(template) / f"{_segment(colour)}.png"
        if exact.is_file():
            return exact
        matches = [
            photo
            for photo in self.template_photos(template)
            if _ends_with_colour_segments(photo.stem, colour)
        ]
        if len(matches) > 1:
            raise AmbiguousColourSuffixError(template, colour, matches)
        return matches[0] if matches else exact

    def template_scene_image(self, template: str) -> Path:
        return self.template_dir(template) / f"{_SCENE_STEM}.png"

    def scene_photo(self, template: str, colour: str | None) -> ScenePhoto:
        if colour is not None:
            return ScenePhoto(path=self.template_base_image(template, colour), map_key=colour)
        return ScenePhoto(path=self.template_scene_image(template), map_key=template)

    def test_designs_dir(self) -> Path:
        return self.root / layout.TEST_DESIGNS_DIR

    def test_design_file(self, name: str) -> Path:
        return self.test_designs_dir() / f"{_segment(name)}.png"

    def test_design_names(self) -> list[str]:
        directory = self.test_designs_dir()
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.png") if p.is_file())

    def renders_dir(self, listing: str) -> Path:
        return self.cache(layout.RENDERS_DIR, _segment(listing))

    def render_file(self, listing: str, template: str, colour: str | None = None) -> Path:
        filename = f"{_segment(colour)}.png" if colour is not None else "scene.png"
        return self.renders_dir(listing) / _segment(template) / filename

    def listing_template_caches(self, listing: str, template: str) -> TemplateCaches:
        return TemplateCaches(
            self.renders_dir(listing) / _segment(template),
            self.preview_dir(listing) / _segment(template),
        )

    def catalog_cache_dir(self) -> Path:
        return self.cache(layout.CATALOG_DIR)

    def market_search_cache_dir(self) -> Path:
        return self.cache(layout.MARKET_DIR, layout.MARKET_SEARCH_DIR)

    def market_stats_cache_dir(self) -> Path:
        return self.cache(layout.MARKET_DIR, layout.MARKET_STATS_DIR)

    def market_snapshot_file(self, listing: str) -> Path:
        return self.cache(
            layout.MARKET_DIR, layout.MARKET_SNAPSHOTS_DIR, f"{_segment(listing)}.json"
        )

    def proposal_file(self, listing: str) -> Path:
        return self.cache(layout.PROPOSALS_DIR, f"{_segment(listing)}.json")

    def preview_dir(self, listing: str) -> Path:
        return self.cache(layout.PREVIEWS_DIR, _segment(listing))

    def scene_cache_dir(self) -> Path:
        return self.cache(layout.SCENES_DIR)

    def ai_image_cache_dir(self) -> Path:
        return self.cache(layout.AI_IMAGES_DIR)

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def prune_previews(self, listing: str, valid: dict[str, set[str]]) -> None:
        root = self.preview_dir(listing)
        if not root.is_dir():
            return
        for directory in root.iterdir():
            if directory.is_dir():
                _prune_template_previews(directory, valid.get(directory.name))

    def preview_file(
        self, listing: str, template: str, colour: str | None, scene_hash: str
    ) -> Path:
        """One scene's full-size preview, content-addressed by its own
        ``scene_hash``: a plan that changes nothing finds the file already
        there, and a stale one stops matching rather than needing to be found
        and deleted by name. ``scene_hash`` goes through :func:`_segment`
        because the preview endpoint resolves through this accessor, never a
        path from the URL; the caller strips the hash's ``sha256:`` prefix."""
        stem = _segment(colour) if colour is not None else "scene"
        filename = f"{stem}-{_segment(scene_hash)}.png"
        return self.preview_dir(listing) / _segment(template) / filename

    def load_listing(self, listing: str) -> Listing:
        return Listing.load(
            self.listing_file(listing),
            currency=self.defaults.etsy.currency,
            read=read_bytes_retrying,
        )

    def load_garment_profile(self, garment_profile: str) -> GarmentProfile:
        return GarmentProfile.load(self.garment_profile_file(garment_profile))

    def load_pricing_plan(self, path: Path) -> PricingPlan:
        return PricingPlan.load(path, currency=self.defaults.etsy.currency)

    def capture_settings(self) -> Settings:
        return Settings.load(self.settings_file())

    def settings_or_problem(self) -> Settings | SettingsProblem:
        try:
            return self.capture_settings()
        except ConfigLoadError as exc:
            return SettingsProblem(str(exc))

    def settings_if_readable(self, *, skipping: str) -> Settings | None:
        settings = self.settings_or_problem()
        if isinstance(settings, SettingsProblem):
            logger.warning("skipped %s: %s", skipping, settings.message)
            return None
        return settings

    def load_exceptions(self) -> ColourExceptions:
        return load_exceptions(self.exceptions_file())


def _prune_template_previews(directory: Path, keep: set[str] | None) -> None:
    if keep is None:
        remove_tree(directory)
        return
    for file in directory.glob("*.png"):
        if file.name not in keep:
            file.unlink()
