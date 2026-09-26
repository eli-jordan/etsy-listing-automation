"""The ``etsy_media`` stage: upload what changed, reorder/detach with one
``image_ids`` PATCH, then the per-colour variation-image links (decisions 5
and 6).

**The manifest is `listing.media`, in order** -- PRD 12's full-replacement
media sync retained, ids now surviving a reorder (decision 5). Each entry's
``ref`` is ``"{template}:{colour}"`` for a colour-matrix entry, the bare
template name for a `single`/`multiple` one, or the entry's own
workspace-relative path for a shared ``common-media/`` asset -- stable across
a re-render, since the render stage's own output path does not appear in it.

**A file that does not exist yet is `pending`, not missing (A26's local
twin).** `desired()` runs at plan time, before any stage has applied anything
this run; if `render` is about to create the file in the *same* `apply`,
`etsy_media`'s own `apply` -- running after it in pipeline order -- finds the
file there. So `apply` re-hashes each file itself at upload time rather than
trusting `desired`'s plan-time hash, and a `pending` entry `plan` still
reports as work, because the run that clears it is this one.

**Drift needs a mapping `plan()` itself is never handed.** Whether a
previously-uploaded image is still on the listing depends on
``lock.remote``'s ref -> id map, and `plan()` only receives
``(desired, applied, live)`` -- so `read_live()` resolves the question itself
(it *is* handed the lockfile) and hands `plan()` the answer, `dangling_refs`,
rather than the raw ids for `plan()` to reconcile blind.

**No `overwrite: true` in-place replace, deliberately.** It is a genuine
optimisation (decision 5) -- skip the `image_ids` PATCH entirely when a
mockup's bytes changed but its position did not -- but decision 6 also
proves the price of it: a replaced image's id changes, and any variation
link still naming the old one goes dangling and invisible until re-asserted.
The two-step upload-then-`image_ids` path this stage takes is the one PRD 12
and PRD 57 describe without qualification, so it is the one built first; the
in-place path is a later, separate change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from etsy_listings.clients.etsy.listings import EtsyListingClient
from etsy_listings.clients.etsy.models import VariationImageLink
from etsy_listings.config.listing import MAX_MEDIA_ENTRIES, TemplateMediaEntry
from etsy_listings.engine.change import Action, Drift, MediaChange, Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, hash_file, to_workspace_relative_posix
from etsy_listings.engine.stage import Blocked, StageApplyResult
from etsy_listings.engine.stages.colour_property import resolve_colour_property
from etsy_listings.engine.stages.etsy_target import (
    check_etsy_shop,
    etsy_listing_id,
    require_etsy_listing_id,
)

IMAGE_IDS_KEY = "etsy_image_ids"
"""This stage's key in ``lock.remote`` (A20) -- keyed by manifest ref, so a
reorder does not churn the ids (decision 5)."""

PENDING = "pending"
"""Stands in for a design's content hash when its render has not happened
yet. Never a real hash's value -- ``hash_file`` always returns a
``sha256:``-prefixed string -- so the two can never collide."""

NO_SHOP_CONSEQUENCE = "this listing's images will not be uploaded to Etsy"


class DesiredImageSnapshot(BaseModel):
    """One manifest entry, as this run wants to send it (A30)."""

    model_config = ConfigDict(frozen=True)

    rank: int
    ref: str
    file: str


class LiveImageSnapshot(BaseModel):
    """One image Etsy actually has, projected back to a ref where possible
    (A30) -- ``ref`` is ``None`` for an image this tool never uploaded."""

    model_config = ConfigDict(frozen=True)

    rank: int | None
    ref: str | None = None
    image_id: int
    url: str | None = None


class EtsyMediaSnapshot(BaseModel):
    """Domain facts for the review (A30): both manifests in full, so the
    frontend can lay out thumbnails and compute *New* / moved / *Removed*
    badges from ``ref`` identity, guided by the per-rank ``MediaChange``s
    ``plan()`` already emits."""

    model_config = ConfigDict(frozen=True)

    desired: tuple[DesiredImageSnapshot, ...]
    live: tuple[LiveImageSnapshot, ...]


class AppliedMediaEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    ref: str
    hash: str
    alt_text: str = ""


class AppliedEtsyMedia(BaseModel):
    """The verbatim last-applied document (A2)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    manifest: tuple[AppliedMediaEntry, ...]
    variation_images: dict[str, str] = {}
    """colour slug -> manifest ref, only when `variation_images:` names a
    template (PRD 56). Empty means the feature is off for this listing."""


@dataclass(frozen=True)
class ManifestEntry:
    ref: str
    source: Path
    content_hash: str
    """A real ``sha256:...`` hash, or :data:`PENDING`."""
    file: str
    """``source``, workspace-relative and forward-slashed (A30) -- what the
    snapshot's ``desired`` side names, computed here rather than in
    ``snapshot()`` because that method is handed no ``ctx`` (a stage's
    ``snapshot`` is pure, like its ``plan``) and so has no workspace root to
    make ``source`` relative to."""
    alt_text: str = ""
    colour: str | None = None
    """The colour this entry depicts, when it comes from a `colour-matrix`
    entry in the `variation_images:` template -- the one fact a swatch needs
    that a render addressing key does not carry (decision 6's "deferred")."""


@dataclass(frozen=True)
class EtsyMediaDesired:
    manifest: tuple[ManifestEntry, ...]
    variation_images_template: str | None
    colours: tuple[str, ...]
    """The listing's own ``colors:``, carried through from ``desired()``
    rather than re-loaded in ``apply()`` -- the ``Stage`` protocol hands
    ``apply()`` no listing name, only what ``desired()`` already resolved."""

    def applied(self) -> AppliedEtsyMedia:
        return AppliedEtsyMedia(
            manifest=tuple(
                AppliedMediaEntry(ref=entry.ref, hash=entry.content_hash, alt_text=entry.alt_text)
                for entry in self.manifest
            ),
            variation_images={
                entry.colour: entry.ref for entry in self.manifest if entry.colour is not None
            },
        )


@dataclass(frozen=True)
class LiveImage:
    """One image Etsy actually has on the listing right now (A30)."""

    rank: int | None
    image_id: int
    url: str | None
    """Etsy's ``url_570xN`` -- the "On Etsy now" column's source for a draft,
    or for an image uploaded by hand in Shop Manager, either of which has no
    local render to fall back on. ``None`` when Etsy has not generated one
    yet, which the frontend falls back from rather than this stage guessing
    at."""
    ref: str | None = None
    """This id projected back to a manifest ref, through ``lock.remote``'s
    ref -> id map -- the same reversal A27 already does for variation-image
    links. ``None`` for an image this tool never uploaded (a hand-added one
    in Shop Manager), which is not a fact ``snapshot()`` can derive on its
    own: it is handed no ``lock``, only what ``read_live`` already resolved."""


@dataclass(frozen=True)
class EtsyMediaLive:
    live_image_ids: frozenset[int]
    dangling_refs: tuple[str, ...]
    """Refs `lock.remote` says were uploaded, whose id is no longer among the
    listing's images -- a replacement or an outside deletion, either way not
    visible any other way (decision 6, measured)."""
    images: tuple[LiveImage, ...] = ()
    """Every image the listing actually carries right now, in Etsy's own
    rank order (A30) -- what the snapshot's ``live`` side is built from.
    Defaulted rather than always populated by every caller, since a stage
    under test through `execute` alone often builds one by hand without a
    real `read_live`."""


def _ref(template: str, colour: str | None) -> str:
    return f"{template}:{colour}" if colour is not None else template


def _manifest_entry(
    ctx: RunContext,
    listing: str,
    entry: TemplateMediaEntry | str,
    *,
    variation_template: str | None,
) -> ManifestEntry:
    workspace = ctx.workspace
    if isinstance(entry, str):
        # A bare string is a file ref, resolved the same way `design:` is:
        # PRD 72's two roots, the workspace or `./` for the listing's own.
        source = workspace.resolve_ref(entry, listing_dir=workspace.listing_dir(listing))
        ref = entry
        colour = None
    else:
        source = workspace.render_file(listing, entry.template, entry.colour)
        ref = _ref(entry.template, entry.colour)
        colour = entry.colour if entry.template == variation_template else None

    content_hash = hash_file(source) if source.is_file() else PENDING
    file = to_workspace_relative_posix(workspace.root, source)
    return ManifestEntry(
        ref=ref, source=source, content_hash=content_hash, file=file, colour=colour
    )


class EtsyMediaStage:
    name = "etsy_media"
    local = False
    applied_model = AppliedEtsyMedia

    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedEtsyMedia | None
    ) -> EtsyMediaDesired | Blocked:
        del applied
        blocked = check_etsy_shop(ctx, consequence=NO_SHOP_CONSEQUENCE)
        if blocked is not None:
            return blocked

        config = ctx.workspace.load_listing(listing)
        if len(config.media) > MAX_MEDIA_ENTRIES:
            return Blocked(
                f"media has {len(config.media)} entries, over Etsy's "
                f"{MAX_MEDIA_ENTRIES}-image limit."
            )

        variation_template = config.etsy.variation_images
        if variation_template is not None and not any(
            isinstance(entry, TemplateMediaEntry) and entry.template == variation_template
            for entry in config.media
        ):
            return Blocked(
                f"etsy.variation_images names {variation_template!r}, which is not "
                f"referenced anywhere in media:."
            )

        manifest = tuple(
            _manifest_entry(ctx, listing, entry, variation_template=variation_template)
            for entry in config.media
        )
        return EtsyMediaDesired(
            manifest=manifest,
            variation_images_template=variation_template,
            colours=tuple(config.colors),
        )

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: AppliedEtsyMedia | None
    ) -> EtsyMediaLive | None:
        """`getListing?includes=Images`, the only working route -- the
        dedicated images endpoint 404s for every id, valid or invented
        (measured). ``None`` without a request when there is no listing id
        yet."""
        del applied
        listing_id = etsy_listing_id(lock)
        if listing_id is None:
            return None
        live = ctx.require_etsy().get_listing(listing_id, include_images=True)
        if live is None:
            return None
        live_ids = frozenset(image.listing_image_id for image in live.images)
        known_ids: dict[str, int] = dict(lock.remote.get(IMAGE_IDS_KEY) or {})
        dangling = tuple(ref for ref, image_id in known_ids.items() if image_id not in live_ids)
        ref_by_image_id = {image_id: ref for ref, image_id in known_ids.items()}
        images = tuple(
            LiveImage(
                rank=image.rank,
                image_id=image.listing_image_id,
                url=image.url_570xN,
                ref=ref_by_image_id.get(image.listing_image_id),
            )
            for image in live.images
        )
        return EtsyMediaLive(live_image_ids=live_ids, dangling_refs=dangling, images=images)

    def plan(
        self,
        desired: EtsyMediaDesired,
        applied: AppliedEtsyMedia | None,
        live: EtsyMediaLive | None,
    ) -> Verdict:
        drift_found = _drift(applied, live)

        if applied is None:
            return Verdict.work(
                _first_run_reason(desired),
                actions=_actions(desired),
                changes=_media_changes(desired, None),
                drift=drift_found,
            )

        wanted = desired.applied()
        order_changed = tuple(e.ref for e in wanted.manifest) != tuple(
            e.ref for e in applied.manifest
        )
        hash_changed = {e.ref: e.hash for e in wanted.manifest} != {
            e.ref: e.hash for e in applied.manifest
        }
        variation_changed = wanted.variation_images != applied.variation_images

        if order_changed or hash_changed or variation_changed:
            return Verdict.work(
                "the media manifest changed",
                actions=_actions(desired),
                changes=_media_changes(desired, applied),
                drift=drift_found,
            )
        if drift_found:
            return Verdict.work(
                "Etsy's images disagree with what was last applied -- re-asserting",
                actions=_actions(desired),
                drift=drift_found,
            )
        return Verdict.no_work(drift=drift_found)

    def snapshot(self, desired: EtsyMediaDesired, live: EtsyMediaLive | None) -> EtsyMediaSnapshot:
        """Both manifests in full (A30) -- the frontend's thumbnails and
        badges are built from this plus the ``MediaChange``s ``plan()``
        already emitted, never from diffing these two lists itself."""
        desired_rows = tuple(
            DesiredImageSnapshot(rank=rank, ref=entry.ref, file=entry.file)
            for rank, entry in enumerate(desired.manifest, start=1)
        )
        live_rows: tuple[LiveImageSnapshot, ...] = ()
        if live is not None:
            live_rows = tuple(
                LiveImageSnapshot(
                    rank=image.rank, ref=image.ref, image_id=image.image_id, url=image.url
                )
                for image in live.images
            )
        return EtsyMediaSnapshot(desired=desired_rows, live=live_rows)

    def apply(
        self,
        ctx: RunContext,
        desired: EtsyMediaDesired,
        applied: AppliedEtsyMedia | None,
        live: EtsyMediaLive | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        client = ctx.require_etsy()
        listing_id = require_etsy_listing_id(lock, to="sync media")
        shop_id = ctx.workspace.defaults.etsy.require_shop_id()

        known_ids: dict[str, int] = dict(lock.remote.get(IMAGE_IDS_KEY) or {})
        live_ids = live.live_image_ids if live is not None else frozenset()
        # The document the engine decoded during planning, not a second read
        # of the same subtree: an upload is skipped only when the bytes match
        # what was *last uploaded*, and that is the only thing that knows.
        applied_hashes = {e.ref: e.hash for e in applied.manifest} if applied is not None else {}

        image_ids: dict[str, int] = {}
        sent_hashes: dict[str, str] = {}
        for rank, entry in enumerate(desired.manifest, start=1):
            if not entry.source.is_file():
                raise MediaNotRenderedError(entry.ref)
            current_hash = hash_file(entry.source)
            existing_id = known_ids.get(entry.ref)
            if (
                existing_id is not None
                and existing_id in live_ids
                and current_hash == applied_hashes.get(entry.ref)
            ):
                image_ids[entry.ref] = existing_id
                sent_hashes[entry.ref] = current_hash
                continue

            ctx.emit(f"uploading {entry.ref}")
            image = client.upload_listing_image(
                shop_id,
                listing_id,
                file_name=entry.source.name,
                contents=entry.source.read_bytes(),
                rank=rank,
                alt_text=entry.alt_text,
            )
            image_ids[entry.ref] = image.listing_image_id
            sent_hashes[entry.ref] = current_hash

        ctx.emit(f"setting image order ({len(image_ids)} images)")
        client.update_listing(
            shop_id, listing_id, {"image_ids": [image_ids[e.ref] for e in desired.manifest]}
        )

        if desired.variation_images_template is not None:
            self._apply_variation_images(ctx, client, shop_id, listing_id, desired, image_ids)

        applied_doc = AppliedEtsyMedia(
            manifest=tuple(
                AppliedMediaEntry(ref=e.ref, hash=sent_hashes[e.ref], alt_text=e.alt_text)
                for e in desired.manifest
            ),
            variation_images={e.colour: e.ref for e in desired.manifest if e.colour is not None},
        )
        return StageApplyResult(
            applied=applied_doc.model_dump(mode="json"), remote={IMAGE_IDS_KEY: image_ids}
        )

    def _apply_variation_images(
        self,
        ctx: RunContext,
        client: EtsyListingClient,
        shop_id: int,
        listing_id: int,
        desired: EtsyMediaDesired,
        image_ids: dict[str, int],
    ) -> None:
        inventory = client.get_listing_inventory(listing_id)
        exceptions = ctx.workspace.load_exceptions()
        colour_property = resolve_colour_property(inventory, desired.colours, exceptions)
        if colour_property is None:
            ctx.emit("variation_images: no single matching colour property on Etsy -- skipped")
            return

        links = [
            VariationImageLink(
                property_id=colour_property.property_id,
                value_id=colour_property.value_id_by_slug[entry.colour],
                image_id=image_ids[entry.ref],
            )
            for entry in desired.manifest
            if entry.colour is not None and entry.colour in colour_property.value_id_by_slug
        ]
        ctx.emit(f"setting {len(links)} variation image link(s)")
        client.update_variation_images(shop_id, listing_id, links)


class MediaNotRenderedError(RuntimeError):
    """A manifest entry's file does not exist when ``apply`` tried to upload
    it. `render` runs earlier in the pipeline and should have produced it in
    this same run; reaching here is a wiring defect."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"cannot upload {ref!r}: its render output does not exist on disk yet.")


def _first_run_reason(desired: EtsyMediaDesired) -> str:
    pending = sum(1 for e in desired.manifest if e.content_hash == PENDING)
    if pending:
        noun = "image" if pending == 1 else "images"
        return f"{len(desired.manifest)} images (pending render for {pending} {noun})"
    return f"{len(desired.manifest)} images, never uploaded"


def _actions(desired: EtsyMediaDesired) -> tuple[Action, ...]:
    return (
        Action(
            description=f"upload {len(desired.manifest)} image(s) and set their order",
            inputs=tuple(str(e.source) for e in desired.manifest),
            missing_outputs=tuple(
                str(e.source) for e in desired.manifest if e.content_hash == PENDING
            ),
        ),
    )


def _media_changes(
    desired: EtsyMediaDesired, applied: AppliedEtsyMedia | None
) -> tuple[MediaChange, ...]:
    """One :class:`~etsy_listings.engine.change.MediaChange` per rank whose
    ref differs between what was last applied and what this run wants (A30).

    Replaces the single "the media manifest changed" reason the plan already
    carried: a reason cannot say *which* image is new, which moved or which
    was dropped, so drawing *New* / *was 2* / *Removed* badges used to mean
    the frontend diffing two ref lists itself (A2, decision 4). Matched by
    **rank**, not by ref -- a ref appearing at a different rank is exactly a
    reorder, and the frontend (which also has both full manifests, from the
    snapshot) is what turns "before ref X, after ref Y" into a moved-from-N
    badge, never this stage.
    """
    wanted_refs = [entry.ref for entry in desired.manifest]
    applied_refs = [entry.ref for entry in applied.manifest] if applied is not None else []
    changes: list[MediaChange] = []
    for rank in range(1, max(len(wanted_refs), len(applied_refs), 0) + 1):
        before = applied_refs[rank - 1] if rank <= len(applied_refs) else None
        after = wanted_refs[rank - 1] if rank <= len(wanted_refs) else None
        if before != after:
            changes.append(MediaChange(rank=rank, before=before, after=after))
    return tuple(changes)


def _drift(applied: AppliedEtsyMedia | None, live: EtsyMediaLive | None) -> tuple[Drift, ...]:
    """A previously-uploaded image no longer on the listing -- an outside
    delete, or a replacement that minted a new id and left the old one
    dangling (decision 6, measured: nothing in the API says a swatch broke)."""
    if applied is None or live is None or not live.dangling_refs:
        return ()
    return (
        Drift(
            path="images",
            last_applied=sorted(live.dangling_refs),
            live="detached",
        ),
    )
