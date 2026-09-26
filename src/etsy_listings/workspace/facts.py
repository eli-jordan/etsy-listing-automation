"""What a local listing check reads off the workspace, read once per request.

`config/listing_validation.py` deliberately takes no workspace: it is pure, so
it can run on every autosave against a draft that is on disk nowhere. Somebody
still has to open the files it checks *against* -- the garment profile a
listing names, every template's real kind and colours -- and that somebody used
to be each check's own caller.

It cost what unowned work costs. ``_describe`` loaded one listing's garment
profile twice, because the issues call and the pricing call each loaded their
own. Worse, the whole template catalogue was re-listed and re-parsed inside
every call, and the listings table makes one call *per row*: opening a table of
twenty listings over twenty templates parsed four hundred ``template.yaml``
files, and did it again on the next paint. Nothing was wrong with any one call;
there was simply no module whose job it was to know that a request needs these
facts once.

That is this module. Construct it once where a request begins and hand it down.

Two different costs, so two different strategies:

* **Templates are gathered eagerly**, in ``gather``, because every check of
  every listing needs the whole map -- there is nothing to defer, and putting
  the O(templates) scan in a constructor is what makes it visible at one call
  site instead of hidden inside a check.
* **Garment profiles are read on demand and kept**, because a request usually
  wants one or two of them and a workspace may hold many. The listings table
  asks for each row's; the picker asks for all of them; neither pays for the
  other's.
* **Videos are probed on demand and kept, by file** (PRD 71), for the same
  reason and one more: a shared clip in ``common-media/`` is named by many
  listings, and opening it once per row would be the four-hundred-parses
  mistake again, with FFmpeg doing the parsing.

It holds the `Workspace` rather than copying paths out of it: reading is
`Workspace`'s job (A8), and a snapshot that resolved its own paths would be a
second place that knows the layout.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing
from etsy_listings.config.listing_validation import TemplateInfo
from etsy_listings.config.media import ProbeFailure, VideoFacts, media_kind
from etsy_listings.render.config import ColourMatrixTemplate, MultipleTemplate
from etsy_listings.workspace.video import probe_video
from etsy_listings.workspace.workspace import InvalidNameError, InvalidRefError, Workspace


class WorkspaceFacts:
    """The workspace as a listing check sees it. Build one per request."""

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

    @classmethod
    def gather(cls, workspace: Workspace) -> WorkspaceFacts:
        """Read the catalogue. The one expensive call, and it is named."""
        return cls(
            workspace,
            garment_profile_names=tuple(workspace.garment_profile_names()),
            templates=_template_info_map(workspace),
        )

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
        """Every video ``listing.media`` names, keyed by the ref it is named by
        -- what `check_videos` reads.

        *listing_dir* rather than a name, because a ``./`` ref is resolved
        against it and the editor's unsaved draft has no name
        (`Workspace.draft_listing_dir`). A ref that will not resolve is a
        :class:`ProbeFailure` carrying the refusal, not a raise: it is still
        a file the seller named, and the banner is where they learn why it
        cannot be read.
        """
        result: dict[str, VideoFacts | ProbeFailure] = {}
        for entry in listing.media:
            if not isinstance(entry, str) or media_kind(entry) != "video":
                continue
            try:
                path = self._workspace.resolve_ref(entry, listing_dir=listing_dir)
            except InvalidRefError as exc:
                result[entry] = ProbeFailure(f"cannot be used: {exc.detail}")
                continue
            if path not in self._probes:
                self._probes[path] = probe_video(path)
            result[entry] = self._probes[path]
        return result

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
    for name in workspace.template_names():
        try:
            config = workspace.load_template_config(name)
        except ConfigLoadError:
            continue
        if isinstance(config, ColourMatrixTemplate):
            colours = frozenset(workspace.template_colours(name))
        elif isinstance(config, MultipleTemplate):
            colours = frozenset(p.colour for p in config.placements if p.colour)
        else:
            colours = frozenset({config.colour}) if config.colour else frozenset()
        result[name] = TemplateInfo(kind=config.kind, colours=colours)
    return result
