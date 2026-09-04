"""Workspace root discovery and path resolution. A8.

The data tree (``shop.yaml``, ``designs/``, ``listings/``,
``mockup-templates/``, ``.cache/``) is a separate directory the user owns, never
this repository. ``Workspace.resolve()`` is the single chokepoint every path
reference in a config file passes through, and it refuses to resolve outside the
workspace root — this is a security boundary (it is also what keeps the UI's
future file-serving endpoints safe), not a tidiness rule.
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from etsy_listings.config.defaults import Defaults
from etsy_listings.config.exceptions import load_exceptions
from etsy_listings.config.listing import Listing
from etsy_listings.config.profile import Profile
from etsy_listings.config.slug import ColourExceptions
from etsy_listings.workspace import layout
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


class Workspace:
    def __init__(self, root: Path, defaults: Defaults) -> None:
        self.root = root
        self.defaults = defaults

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
        listings = self.root / layout.LISTINGS_DIR
        if not listings.is_dir():
            return []
        return sorted(p.name for p in listings.iterdir() if (p / layout.LISTING_FILE).is_file())

    def listing_dir(self, listing: str) -> Path:
        return self.root / layout.LISTINGS_DIR / _segment(listing)

    def listing_file(self, listing: str) -> Path:
        return self.listing_dir(listing) / layout.LISTING_FILE

    def lock_file(self, listing: str) -> Path:
        return self.listing_dir(listing) / layout.LOCK_FILE

    def design_file(self, design: str) -> Path:
        return self.root / layout.DESIGNS_DIR / f"{_segment(design)}.png"

    def profile_names(self) -> list[str]:
        profiles = self.root / layout.PROFILES_DIR
        if not profiles.is_dir():
            return []
        return sorted(p.stem for p in profiles.glob("*.yaml") if p.is_file())

    def profile_file(self, profile: str) -> Path:
        return self.root / layout.PROFILES_DIR / f"{_segment(profile)}.yaml"

    def exceptions_file(self) -> Path:
        return self.root / layout.EXCEPTIONS_FILE

    def env_file(self) -> Path:
        """The workspace's gitignored ``.env``. Secrets live in the *workspace*,
        never in this repository -- see ``config/secrets.py``."""
        return self.root / layout.ENV_FILE

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

    def template_config_file(self, template: str) -> Path:
        return self.template_dir(template) / layout.TEMPLATE_FILE

    def template_derived_dir(self, template: str) -> Path:
        return self.template_dir(template) / layout.DERIVED_DIR

    def template_base_image(self, template: str, colour: str) -> Path:
        """``colour-matrix``-kind templates only (PRD 7a): the mockup filename
        *is* the slugified colour name."""
        return self.template_dir(template) / f"{_segment(colour)}.png"

    def template_scene_image(self, template: str) -> Path:
        """``multiple``/``single``-kind templates: exactly one photo, fixed
        filename -- there's no per-colour name to derive it from."""
        return self.template_dir(template) / "scene.png"

    def test_designs_dir(self) -> Path:
        """Where the calibrator's uploaded test targets live (A16). Separate
        from ``designs/``, which holds artwork that actually ships."""
        return self.root / layout.TEST_DESIGNS_DIR

    def test_design_file(self, name: str) -> Path:
        return self.test_designs_dir() / f"{_segment(name)}.png"

    def render_file(self, listing: str, template: str, colour: str | None = None) -> Path:
        """Namespaced by template: a listing can reference several templates
        (item 4), including more than one ``colour-matrix``-kind set, so a
        bare colour slug alone is not always unique across them. Mirrors each
        template's own scene-naming convention, just namespaced --
        ``{colour}.png`` under the template for ``colour-matrix`` kind (pass
        ``colour``), ``scene.png`` for ``multiple``/``single`` kind (omit
        ``colour`` -- exactly one output, nothing to disambiguate)."""
        filename = f"{_segment(colour)}.png" if colour is not None else "scene.png"
        return self.cache(layout.RENDERS_DIR, _segment(listing), _segment(template), filename)

    def catalog_cache_dir(self) -> Path:
        return self.cache(layout.CATALOG_DIR)

    # ------------------------------------------------------------------
    # Reading the tree's config files. The workspace already owns
    # shop.yaml, so it is also the natural place to load the files whose
    # validation depends on it -- callers no longer have to remember to pass
    # `currency=` to every listing load, which was the one argument it was
    # possible to get quietly wrong.
    # ------------------------------------------------------------------

    def load_listing(self, listing: str) -> Listing:
        return Listing.load(self.listing_file(listing), currency=self.defaults.currency)

    def load_profile(self, profile: str) -> Profile:
        return Profile.load(self.profile_file(profile))

    def load_exceptions(self) -> ColourExceptions:
        return load_exceptions(self.exceptions_file())
