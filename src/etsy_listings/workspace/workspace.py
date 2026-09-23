"""Workspace root discovery and path resolution. A8.

The data tree (``shop.yaml``, ``designs/``, ``listings/``,
``mockup-templates/``, ``.cache/``) is a separate directory the user owns, never
this repository. ``Workspace.resolve()`` is the single chokepoint every path
reference in a config file passes through, and it refuses to resolve outside the
workspace root — this is a security boundary (it is also what keeps the UI's
future file-serving endpoints safe), not a tidiness rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import yaml
from pydantic import ValidationError

from etsy_listings.config.defaults import Defaults
from etsy_listings.config.description import DescriptionConfig, compose_description
from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.exceptions import load_exceptions
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing
from etsy_listings.config.pricing_plan import PricingPlan
from etsy_listings.config.slug import ColourExceptions

# `template.yaml` is render geometry and render settings from top to bottom, so
# its models belong to `render`, next to the passes that consume them -- not to
# `config`, which owns the commercial/product files. Loading it here is the same
# edge `load_listing` already has to `config`: the workspace knows where every
# file lives, and asks whichever module owns a file's shape to parse it.
from etsy_listings.render.config import AnyTemplate, dump_template_config
from etsy_listings.render.config import load_template_config as parse_template_config
from etsy_listings.workspace import layout
from etsy_listings.workspace.common_copy import (
    CommonCopyDocument,
    CommonCopyError,
    parse_common_copy,
)
from etsy_listings.workspace.userpath import to_native_path


class WorkspaceNotFoundError(FileNotFoundError):
    def __init__(self, start: Path) -> None:
        super().__init__(
            f"no '{layout.SHOP_FILE}' found in {start} or any parent directory; "
            f"pass --root, set {layout.ROOT_ENV_VAR}, or run from inside a workspace"
        )


class PathEscapesWorkspaceError(ValueError):
    def __init__(self, ref: str, root: Path) -> None:
        super().__init__(f"path {ref!r} escapes the workspace root ({root})")


@dataclass(frozen=True)
class DescriptionResolution:
    """One common-copy read, shared by the editor's preview and its issue check."""

    composed: str
    error: CommonCopyError | None = None


class InvalidNameError(ValueError):
    """A listing/template/colour name that is not a single path segment.

    Names come from config files and, in the UI's case, from URLs, so this is
    the check that stops ``../../etc/passwd`` ever being joined onto the
    workspace root in the first place.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"{name!r} is not a valid name: expected a single path segment")


def _segment(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise InvalidNameError(name)
    return name


class AmbiguousColourSuffixError(ValueError):
    """More than one photo in a template's directory ends in the same colour
    slug's hyphen segments, so :func:`Workspace.template_base_image`'s
    trailing-segment fallback (PRD 7a) has no single answer. Refused rather
    than guessed at -- an arbitrary pick here would ship the wrong photo."""

    def __init__(self, template: str, colour: str, candidates: list[Path]) -> None:
        names = ", ".join(sorted(p.name for p in candidates))
        super().__init__(
            f"template {template!r}: colour {colour!r} matches more than one photo by "
            f"filename suffix ({names}); rename the files so one matches exactly, or add "
            f"an exceptions.yaml entry"
        )


def _ends_with_colour_segments(stem: str, colour: str) -> bool:
    """Does ``stem``'s hyphen segments end with ``colour``'s own segments?

    Segment-aligned, not a raw substring test: colour ``blue`` must not match
    filename ``flo-blue`` because ``"blue"`` appears inside it, only because
    ``"blue"`` is the filename's own trailing segment. A raw ``str.endswith``
    would additionally match a colour ``"o-blue"`` against the same file,
    which is not a colour, just a coincidence of characters.
    """
    stem_segments = stem.split("-")
    colour_segments = colour.split("-")
    if len(colour_segments) > len(stem_segments):
        return False
    return stem_segments[len(stem_segments) - len(colour_segments) :] == colour_segments


def _looks_like_windows_absolute(ref: str) -> bool:
    """Catch drive-relative (``C:foo``) and UNC (``\\\\server\\share``) forms.

    ``PureWindowsPath("C:foo").is_absolute()`` is ``False`` -- Windows calls that
    "drive-relative", not absolute, because it has a drive but no root. It still
    names a location outside anything we'd consider workspace-relative, and a
    plain POSIX-style escape check would miss it entirely, so it needs its own
    test.
    """
    p = PureWindowsPath(ref)
    return p.drive != "" or ref.startswith("\\\\") or ref.startswith("//")


_SCENE_STEM = "scene"
"""The fixed filename a ``multiple``/``single``-kind template's one photo
takes. Named once because two accessors turn on it: the scene image itself,
and :meth:`Workspace.template_photos`, which is everything *but* it."""


@dataclass(frozen=True)
class ScenePhoto:
    """A scene's blank mockup photo, and the name its derived maps cache under
    (see :meth:`Workspace.scene_photo`)."""

    path: Path
    map_key: str


def _make_writable(func: Callable[[str], object], path: str, exc: BaseException) -> None:
    """`shutil.rmtree`'s ``onexc`` hook: clear a read-only flag and try again.

    Windows refuses `os.rmdir` on a directory carrying
    ``FILE_ATTRIBUTE_READONLY`` with a bare ``Access is denied``, and whole
    trees arrive carrying it -- a workspace kept inside a Google Drive folder
    is the case that found this, where every directory Drive syncs has the
    attribute set. Nothing about such a tree is genuinely protected: the files
    inside delete fine, and only the final `rmdir` of each directory fails,
    which is what makes the traceback so hard to read.

    Adds the owner-write bit rather than replacing the mode, so one call is
    right on both platforms this project is tested on: on Windows it clears
    the attribute, and on POSIX it restores write permission to a directory
    whose own entries could not otherwise be unlinked. Anything that is not a
    `PermissionError`, and any retry that fails again, is raised -- this
    widens exactly one refusal, not every one.
    """
    if not isinstance(exc, PermissionError):
        raise exc
    os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    """`shutil.rmtree`, surviving a read-only directory (see
    :func:`_make_writable`).

    Every tree this project deletes is one it created and owns -- a listing's
    directory, its render cache, its previews -- so a read-only flag on one is
    an artefact of the filesystem it sits on, never an instruction from the
    user. The one place that rule would not hold is a tree named by a user,
    and there is no such delete.
    """
    shutil.rmtree(path, onexc=_make_writable)


class Workspace:
    def __init__(self, root: Path, defaults: Defaults) -> None:
        self.root = root
        self.defaults = defaults

    def browser_storage_id(self) -> str:
        """Stable workspace identity without exposing its absolute path to the UI.

        PRD 4 scopes pending SEO proposals to a workspace and listing. Shop
        name cannot identify a workspace: two roots can use the same name.
        """
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

        # ETSY_LISTINGS_ROOT arrives as a raw string, so it may still be in
        # Cygwin form. (--root gets the same treatment in the CLI, which must
        # translate before pathlib touches the string -- see to_native_path.)
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
        """Resolve ``ref`` (as written in a config file) to an absolute path.

        ``relative_to`` is the directory the reference is written relative to
        (typically the config file's own directory), matching how the PRD's
        example configs use ``../../designs/take-a-hike.png``-style paths.
        Raises :class:`PathEscapesWorkspaceError` if the result would fall
        outside :attr:`root`.
        """
        if Path(ref).is_absolute() or _looks_like_windows_absolute(ref):
            raise PathEscapesWorkspaceError(ref, self.root)

        candidate = (relative_to / ref).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PathEscapesWorkspaceError(ref, self.root) from exc
        return candidate

    def cache(self, *parts: str) -> Path:
        return self.root.joinpath(layout.CACHE_DIR, *parts)

    # ------------------------------------------------------------------
    # Layout accessors.
    #
    # These are the *only* place that knows the shape of the workspace tree.
    # Everything else asks for "this listing's lockfile" rather than joining
    # "listings" / name / "state.lock.json" for itself, so renaming a
    # directory is a one-line change here and the UI cannot accidentally grow
    # its own path handling (see `_segment`).
    # ------------------------------------------------------------------

    def listing_names(self) -> list[str]:
        """Directories that still have ``listing.yaml``, or a lockfile with
        the yaml gone (PRD 67: the row still appears, ``Blocked``). An empty
        directory is not a listing.
        """
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

    def remove_listing(self, listing: str) -> None:
        """Wipe ``listings/{name}/``, ``.cache/renders/{name}/`` (PRD 63) and
        ``.cache/previews/{name}/`` (A32).

        Designs, garment profiles and pricing plans stay -- they are reusable.
        """
        for path in (
            self.listing_dir(listing),
            self.renders_dir(listing),
            self.preview_dir(listing),
        ):
            if path.is_dir():
                remove_tree(path)

    def listing_dir(self, listing: str) -> Path:
        return self.root / layout.LISTINGS_DIR / _segment(listing)

    def listing_file(self, listing: str) -> Path:
        return self.listing_dir(listing) / layout.LISTING_FILE

    def design_content_hash(self, design: Mapping[str, str], *, listing_dir: Path) -> str | None:
        """Content identity for the design the editor and SEO request see.

        Keys and refs are sorted, and the hash contains no absolute path. A
        missing secondary file gets a stable marker so changes to readable
        artwork still change the identity of an incomplete draft.
        """
        if not design:
            return None
        digest = hashlib.sha256()
        for key, ref in sorted(design.items()):
            content_hash: str | None = None
            try:
                path = self.resolve(ref, relative_to=listing_dir)
                file_digest = hashlib.sha256()
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        file_digest.update(chunk)
                content_hash = file_digest.hexdigest()
            except (OSError, PathEscapesWorkspaceError):
                pass
            entry = json.dumps((key, ref, content_hash), ensure_ascii=False)
            digest.update(entry.encode("utf-8"))
        return digest.hexdigest()

    def lock_file(self, listing: str) -> Path:
        return self.listing_dir(listing) / layout.LOCK_FILE

    def designs_dir(self) -> Path:
        return self.root / layout.DESIGNS_DIR

    def design_file(self, design: str) -> Path:
        return self.designs_dir() / f"{_segment(design)}.png"

    def design_files(self) -> list[Path]:
        """Every ``designs/*.png``, the artwork a listing can be built from.

        Paths rather than names, because the ``new`` picker orders them by
        modification time -- a design is usually made minutes before the
        listing that ships it -- and only a path carries that. Flat, not
        recursive: :meth:`design_file` derives one fixed path per name, so a
        nested design would be listed and then not resolvable.
        """
        designs = self.designs_dir()
        if not designs.is_dir():
            return []
        return sorted(p for p in designs.glob("*.png") if p.is_file())

    def common_media_dir(self) -> Path:
        return self.root / layout.COMMON_MEDIA_DIR

    def common_media_file(self, asset: str) -> Path:
        return self.common_media_dir() / f"{_segment(asset)}.png"

    def common_media_files(self) -> list[Path]:
        """Every ``common-media/*.png``: the shared assets a listing can put in
        ``media:`` as a bare path (a sizing chart, care instructions), as
        opposed to a rendered mockup.

        PNG only and flat, for the same reason :meth:`design_files` is:
        :meth:`common_media_file` derives one fixed path per name, so anything
        listed here that it could not resolve would be offered and then fail.
        Sorted by name rather than mtime -- unlike a design, a shared asset is
        written once and reused for years, so recency says nothing useful.
        """
        shared = self.common_media_dir()
        if not shared.is_dir():
            return []
        return sorted((p for p in shared.glob("*.png") if p.is_file()), key=lambda p: p.name)

    def seo_prompt_file(self) -> Path:
        """``prompts/seo.md`` -- the seller-editable AI SEO prompt (AI SEO
        implementation plan, PR3). Reading, seeding, and appending the
        delimited JSON context around it are the ``ai`` package's job; this
        accessor only names the file, the same split every other layout
        accessor draws."""
        return self.root / layout.PROMPTS_DIR / layout.SEO_PROMPT_FILE

    def brief_prompt_file(self) -> Path:
        """``prompts/brief.md`` -- the seller-editable prompt that drafts a
        listing brief from its design image (PRD 68). Same split as
        :meth:`seo_prompt_file`: this accessor only names the file."""
        return self.root / layout.PROMPTS_DIR / layout.BRIEF_PROMPT_FILE

    def common_copy_dir(self) -> Path:
        return self.root / layout.COMMON_COPY_DIR

    def common_copy_file(self, ref: str) -> Path:
        """Verify a `description.ref` and resolve it -- beneath
        `common-copy/` only (PRD's description model).

        Unlike `design:`/`pricing_plan:` refs, which are written relative to
        the listing's own directory, a common-copy ref is portable: written
        once, relative to the workspace root, the same wherever it is
        referenced from (`common-copy/comfort-colors.md`, never
        `../../common-copy/...`). It still goes through :meth:`resolve` for
        the general escape checks (absolute paths, `..` past the root,
        Windows drive forms), plus one more: the result must actually land
        inside :meth:`common_copy_dir`, so `common-copy/../listings/x` -- inside
        the workspace, but not common copy -- is refused exactly like an
        escape, rather than quietly resolving to someone else's file.
        """
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
        """Every ``common-copy/*.md``: the reusable description bodies a
        listing can point ``description.ref`` at (AI SEO implementation plan,
        PR6's common-copy selector). Flat and Markdown-only, for the same
        reason :meth:`common_media_files` is -- :meth:`common_copy_file`
        derives one fixed path per name, so anything listed here that it
        could not resolve would be offered and then fail. Sorted by name: a
        common-copy file, like a shared image, is written once and reused for
        years, so recency says nothing useful about it.
        """
        shared = self.common_copy_dir()
        if not shared.is_dir():
            return []
        return sorted(p for p in shared.glob("*.md") if p.is_file())

    def load_common_copy(self, ref: str) -> CommonCopyDocument:
        """A `description.ref`'s parsed front matter and body.

        The one place a common-copy file's bytes are read: `common_copy.py`'s
        :func:`~etsy_listings.workspace.common_copy.parse_common_copy` owns the
        parsing itself (pure, tested directly against string fixtures), and
        this is the I/O around it -- the same split `load_template_config`
        already draws between reading `template.yaml` and parsing it.
        """
        path = self.common_copy_file(ref)
        if not path.is_file():
            raise CommonCopyError(f"{ref!r}: file not found")
        return parse_common_copy(ref, path.read_text(encoding="utf-8"))

    def resolve_description(self, description: DescriptionConfig) -> DescriptionResolution:
        """Resolve a description once, retaining both its preview and any ref error.

        The editor needs both facts from the same file read. Deployment uses
        :meth:`compose_description`, which raises the error from this result.
        """
        text = description.text
        if description.ref is not None:
            try:
                text = self.load_common_copy(description.ref).body
            except CommonCopyError as exc:
                return DescriptionResolution(compose_description(description.lead, None), exc)
        return DescriptionResolution(compose_description(description.lead, text))

    def compose_description(self, description: DescriptionConfig) -> str:
        """The final concrete `etsy.description` text -- the one shared
        resolver every deployment reader (Printify, Etsy, snapshots, diffs,
        local validation) is required to call, rather than each re-deriving
        it. The editor reads :meth:`resolve_description` once for both its
        preview and its issue check (docs/ai-seo-implementation-plan.md,
        "Description and common-copy boundaries").

        Loads ``description.ref`` through :meth:`load_common_copy` when one is
        set -- raising :class:`~etsy_listings.workspace.common_copy.CommonCopyError`
        for a caller to turn into a `Blocked` stage or a banner issue -- then
        hands the resolved lead/body pair to the pure
        :func:`~etsy_listings.config.description.compose_description`, which
        knows nothing about `ref` or the filesystem.
        """
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
        """Every ``*.yaml`` under ``pricing-plans/``, recursively -- nested
        layouts are allowed here (unlike ``garment-profiles/``/``mockup-templates/``),
        since a plan's directory has no enforced meaning; it's purely where
        the user chose to file it. Discovery only -- a listing may reference
        a plan anywhere in the workspace via its relative path, the same
        flexibility ``design:`` already has."""
        root = self.pricing_plans_dir()
        if not root.is_dir():
            return []
        return sorted(p for p in root.rglob("*.yaml") if p.is_file())

    def exceptions_file(self) -> Path:
        return self.root / layout.EXCEPTIONS_FILE

    def env_file(self) -> Path:
        """The workspace's gitignored ``.env``. Secrets live in the *workspace*,
        never in this repository -- see ``config/secrets.py``."""
        return self.root / layout.ENV_FILE

    def etsy_tokens_file(self) -> Path:
        """Where ``auth`` leaves the OAuth tokens, and where every later run
        reads them from.

        ``auth`` itself cannot use this accessor -- it runs before there is a
        ``shop.yaml`` to discover a workspace by, so it joins the same two
        layout constants against the root it was given (PRD 49). This exists
        for everything downstream of it, which does have a workspace.
        """
        return self.root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE

    def templates_dir(self) -> Path:
        return self.root / layout.MOCKUP_TEMPLATES_DIR

    def template_names(self, *, include_uncalibrated: bool = False) -> list[str]:
        """Templates that are actually usable -- a directory only counts once
        the calibrator has written its ``template.yaml``, the same rule
        :meth:`listing_names` applies to ``listing.yaml``. An uncalibrated
        directory has no kind and no geometry, so offering it would only move
        the failure later.

        ``include_uncalibrated=True`` lifts that filter for the one caller
        that has to see past it: the calibrator UI is what *writes*
        ``template.yaml``, so filtering on it there would hide exactly the
        directories that still need calibrating.
        """
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
        """Is there a directory for this template at all?

        Distinct from :meth:`template_names`'s filter, which asks whether one
        has been *calibrated*. The calibrator needs the weaker question: a
        folder of photos with no ``template.yaml`` is exactly what it exists
        to turn into a template.
        """
        return self.template_dir(template).is_dir()

    def template_photos(self, template: str) -> list[Path]:
        """Every mockup photo in the template's directory except the scene,
        sorted.

        For a ``colour-matrix`` set these are the colours; for the other two
        kinds it is what is there *before* calibration renames the single
        photo to ``scene.png``. Either way the filenames are the template's
        content, so reading them is a layout question and belongs here -- the
        calibrator used to glob for them itself, which is the one place
        anything but this module knew what a template directory looks like.
        """
        directory = self.template_dir(template)
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.glob("*.png") if p.stem != _SCENE_STEM)

    def template_colours(self, template: str) -> list[str]:
        """The colours a ``colour-matrix`` set offers, read from its filenames.

        PRD 7a: the mockup filename *is* the slugified colour name, which is
        why this is a directory listing and not a lookup table.
        """
        return [photo.stem for photo in self.template_photos(template)]

    def template_preview_photo(self, template: str) -> Path | None:
        """The one photo that stands for the whole template, or ``None``.

        Which one hardly matters: a colour-matrix set's colours are the same
        garment at the same size, and the other two kinds have exactly one
        photo. So this takes ``scene.png`` when there is one and the first
        colour otherwise -- **without reading the config**, which is what lets
        it answer for a directory that has not been given a kind yet.
        """
        scene = self.template_scene_image(template)
        if scene.is_file():
            return scene
        return next(iter(self.template_photos(template)), None)

    def template_config_file(self, template: str) -> Path:
        return self.template_dir(template) / layout.TEMPLATE_FILE

    def template_derived_dir(self, template: str) -> Path:
        return self.template_dir(template) / layout.DERIVED_DIR

    def template_base_image(self, template: str, colour: str) -> Path:
        """``colour-matrix``-kind templates only (PRD 7a): the mockup filename
        *is* the slugified colour name.

        Falls back to a trailing-segment match against the directory's actual
        photos when no exact ``{colour}.png`` exists -- a vendor photo pack
        delivered as ``comfort-colors-flat-lay-black.png`` still resolves
        colour ``black``, without renaming every file to drop the shared
        prefix. Only when exactly one photo qualifies: zero leaves the
        (non-existent) exact path for the caller's own "no mockup base image"
        error, and more than one raises rather than guessing.
        """
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
        """``multiple``/``single``-kind templates: exactly one photo, fixed
        filename -- there's no per-colour name to derive it from."""
        return self.template_dir(template) / f"{_SCENE_STEM}.png"

    def scene_photo(self, template: str, colour: str | None) -> ScenePhoto:
        """Which photo a scene composites over, and what its derived maps are
        cached under.

        The two answers are one rule, so they are given together: a
        colour-matrix scene has a photo *per colour* and therefore a height
        and luminance map per colour, while the other two kinds have one of
        each for the whole template. Both the render stage and the
        calibrator's preview endpoint ask here, rather than each re-deriving
        it from the template's kind -- which is what previously let the two
        drift.
        """
        if colour is not None:
            return ScenePhoto(path=self.template_base_image(template, colour), map_key=colour)
        return ScenePhoto(path=self.template_scene_image(template), map_key=template)

    def test_designs_dir(self) -> Path:
        """Where the calibrator's uploaded test targets live (A19). Separate
        from ``designs/``, which holds artwork that actually ships."""
        return self.root / layout.TEST_DESIGNS_DIR

    def test_design_file(self, name: str) -> Path:
        return self.test_designs_dir() / f"{_segment(name)}.png"

    def test_design_names(self) -> list[str]:
        """Every uploaded calibration target, by the id the library offers it
        under -- which is its filename stem, the same way
        :meth:`test_design_file` resolves one back."""
        directory = self.test_designs_dir()
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.png") if p.is_file())

    def renders_dir(self, listing: str) -> Path:
        """Every render this listing has cached.

        Exists because the render cache is keyed by listing *name*, so renaming
        a listing has to move it -- and the rename endpoint knowing how to spell
        `.cache/renders/{listing}` itself would be the second place that knows
        where renders live."""
        return self.cache(layout.RENDERS_DIR, _segment(listing))

    def render_file(self, listing: str, template: str, colour: str | None = None) -> Path:
        """Namespaced by template: a listing can reference several templates
        (item 4), including more than one ``colour-matrix``-kind set, so a
        bare colour slug alone is not always unique across them. Mirrors each
        template's own scene-naming convention, just namespaced --
        ``{colour}.png`` under the template for ``colour-matrix`` kind (pass
        ``colour``), ``scene.png`` for ``multiple``/``single`` kind (omit
        ``colour`` -- exactly one output, nothing to disambiguate)."""
        filename = f"{_segment(colour)}.png" if colour is not None else "scene.png"
        return self.renders_dir(listing) / _segment(template) / filename

    def catalog_cache_dir(self) -> Path:
        return self.cache(layout.CATALOG_DIR)

    def preview_dir(self, listing: str) -> Path:
        """Every preview this listing currently holds, one subdirectory per
        template -- the same split :meth:`renders_dir` uses, since a preview
        is the same pixels :meth:`render_file` would produce, just rendered
        ahead of ``apply`` (A32). Sibling to the render cache, not nested in
        it, so :meth:`remove_listing` can wipe one independently of the other."""
        return self.cache(layout.PREVIEWS_DIR, _segment(listing))

    def preview_file(
        self, listing: str, template: str, colour: str | None, scene_hash: str
    ) -> Path:
        """One scene's full-size preview, content-addressed by its own
        ``scene_hash`` (A32): a plan that changes nothing finds the file
        already there, and a stale one simply stops matching rather than
        needing to be found and deleted by name. Filename mirrors
        :meth:`render_file`'s own convention -- the colour for a
        ``colour-matrix`` scene, ``scene`` otherwise -- with the hash appended
        so two different states of the same scene never collide. ``scene_hash``
        goes through :func:`_segment` like every other name here: it is a
        security boundary (PRD 20's future preview endpoint resolves through
        this accessor, never a path from the URL), not just a naming rule, so
        it refuses anything that is not a single, filesystem-safe segment --
        which is exactly why the caller strips the hash's ``sha256:`` prefix
        before handing it here."""
        stem = _segment(colour) if colour is not None else "scene"
        filename = f"{stem}-{_segment(scene_hash)}.png"
        return self.preview_dir(listing) / _segment(template) / filename

    # ------------------------------------------------------------------
    # Reading the tree's config files. The workspace already owns
    # shop.yaml, so it is also the natural place to load the files whose
    # validation depends on it -- callers no longer have to remember to pass
    # `currency=` to every listing load, which was the one argument it was
    # possible to get quietly wrong.
    # ------------------------------------------------------------------

    def load_listing(self, listing: str) -> Listing:
        return Listing.load(self.listing_file(listing), currency=self.defaults.etsy.currency)

    def load_garment_profile(self, garment_profile: str) -> GarmentProfile:
        return GarmentProfile.load(self.garment_profile_file(garment_profile))

    def load_pricing_plan(self, path: Path) -> PricingPlan:
        """Attaches workspace currency, like
        ``load_garment_profile``/``load_listing``
        -- but path-based, not bare-name: pricing-plan refs are path refs
        (see ``Listing.pricing_plan``'s docstring), so resolving a name to a
        path is the caller's job, the same point ``design:`` refs are
        resolved. This method only owns "attach currency, wrap load errors"."""
        return PricingPlan.load(path, currency=self.defaults.etsy.currency)

    def load_exceptions(self) -> ColourExceptions:
        return load_exceptions(self.exceptions_file())

    def load_template_config(self, template: str) -> AnyTemplate:
        """One ``template.yaml``, parsed into whichever of the three kinds it is.

        The read used to be open-coded at each of its four call sites -- the
        render stage's ``desired`` and ``apply``, the calibrator's endpoints
        and ``new``'s kind lookup -- each doing its own
        ``yaml.safe_load(path.read_text(...))``. That is exactly the joining
        of a layout that the layout accessors above exist to prevent, so it
        lives here with ``load_listing`` and ``load_garment_profile``.
        """
        path = self.template_config_file(template)
        if not path.is_file():
            raise ConfigLoadError(path, "template config not found -- calibrate it with `ui` first")
        try:
            return parse_template_config(yaml.safe_load(path.read_text(encoding="utf-8")))
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

    def save_template_config(self, template: str, config: AnyTemplate) -> None:
        """Write ``template.yaml``. The calibrator is the only caller -- it is
        what produces this file (PRD: the calibrator's artefact) -- but the
        path and the serialisation belong here, beside the read."""
        path = self.template_config_file(template)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(dump_template_config(config), sort_keys=False), encoding="utf-8"
        )
