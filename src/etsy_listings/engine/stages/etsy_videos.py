"""The ``etsy_videos`` stage: a listing's videos, placed where `media:` puts
them (PRD 72, phase-3-etsy.md decision 9).

Etsy has no position for a video -- no rank, no ordering call. Where one
shows follows from attach order, measured by eye in Shop Manager: the video
attached longest is featured at position 2, and any other is anchored after
the number of images the listing had when it was attached. So `media:` is
read for two facts, the featured video (the one at position 2) and the
second video's anchor (the images before it), and `apply` brings the
listing to them in decision 9's four steps:

1. **Sweep** every video on the listing that is not one of ours, `active` or
   `inactive` -- a stranger may be holding a slot. Foreign videos never make
   the stage run on their own, as `image_ids` treats foreign images.
2. **Featured.** If it differs from the one last applied, delete both of
   ours, because a survivor would be promoted, then attach it: uploaded when
   its bytes are new, re-attached by id when Etsy already has them.
3. **Second.** If it, its bytes or its anchor changed -- or step 2 ran --
   delete it, cut `image_ids` to the first *n* images, attach it, and put the
   full list back.
4. **Swatches.** Detaching an image deletes its swatch link for good, so
   step 3 is always followed by re-setting them, through the helper
   `etsy_media` uses.

**A position changed by hand in Shop Manager is invisible**: the API reports
none, so there is nothing for `plan` to compare. Drift is what the API *can*
show -- one of ours missing or `inactive` -- and it is healed by uploading
that video again rather than trusting an id Etsy has stopped showing.

**Its own stage, not a branch of `etsy_media`.** Videos have their own
applied model, their own id map and their own daily budget (ten
associations per listing, re-attaches included): a budget refusal fails this
stage alone, after `etsy_media`'s ids are already recorded (A29), so the
next run re-uploads no image.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from etsy_listings.clients.etsy.listings import EtsyListingClient
from etsy_listings.config.media import media_kind
from etsy_listings.engine.change import Action, Drift, FieldChange, Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, hash_file, to_workspace_relative_posix
from etsy_listings.engine.stage import Blocked, StageApplyResult
from etsy_listings.engine.stages.etsy_media import IMAGE_IDS_KEY
from etsy_listings.engine.stages.etsy_target import (
    check_etsy_shop,
    etsy_listing_id,
    require_etsy_listing_id,
)
from etsy_listings.engine.stages.gates import check_videos
from etsy_listings.engine.stages.variation_links import (
    manifest_ref,
    set_variation_images,
    swatch_refs,
)
from etsy_listings.workspace.facts import WorkspaceFacts

VIDEO_IDS_KEY = "etsy_video_ids"
"""This stage's key in ``lock.remote`` (A20): ref -> Etsy ``video_id``, which
is what makes a re-attach by id possible when only the layout changed."""

NO_SHOP_CONSEQUENCE = "this listing's videos will not be uploaded to Etsy"


class AppliedVideo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    ref: str
    hash: str
    after_images: int | None = None
    """The second video's anchor; ``None`` for the featured one, whose place
    is fixed at position 2."""


class AppliedEtsyVideos(BaseModel):
    """The verbatim last-applied document (A2): featured first."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    videos: tuple[AppliedVideo, ...] = ()


@dataclass(frozen=True)
class DesiredVideo:
    ref: str
    source: Path
    content_hash: str
    file: str
    """``source``, workspace-relative and forward-slashed, for the snapshot."""
    after_images: int | None = None

    def applied(self) -> AppliedVideo:
        return AppliedVideo(ref=self.ref, hash=self.content_hash, after_images=self.after_images)


@dataclass(frozen=True)
class EtsyVideosDesired:
    videos: tuple[DesiredVideo, ...]
    """Featured first, then the second, if any."""
    image_refs: tuple[str, ...] = ()
    """Every image in `media:` order, as ``etsy_image_ids`` keys them: what
    step 3 cuts `image_ids` from and restores it to."""
    swatches: tuple[tuple[str, str], ...] = ()
    """colour -> image ref pairs from `variation_images:` (PRD 56), re-set
    after every cut."""
    colours: tuple[str, ...] = ()

    def applied(self) -> AppliedEtsyVideos:
        return AppliedEtsyVideos(videos=tuple(video.applied() for video in self.videos))


@dataclass(frozen=True)
class LiveVideo:
    video_id: int
    state: str | None
    ref: str | None
    """Ours, projected back through ``etsy_video_ids``; ``None`` for a
    foreign one."""
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class EtsyVideosLive:
    videos: tuple[LiveVideo, ...]
    """Every video on the listing, ours and foreign, `inactive` included."""
    missing_refs: tuple[str, ...] = ()
    """Refs ``etsy_video_ids`` records whose video is no longer listed."""

    @property
    def drifted_refs(self) -> frozenset[str]:
        """Ours, missing or `inactive`: the drift the API can show."""
        inactive = {v.ref for v in self.videos if v.ref is not None and v.state != "active"}
        return frozenset({*self.missing_refs, *inactive})


class DesiredVideoSnapshot(BaseModel):
    """One video as this run wants to place it (A30)."""

    model_config = ConfigDict(frozen=True)

    ref: str
    file: str
    after_images: int | None = None


class LiveVideoSnapshot(BaseModel):
    """One video Etsy has on the listing (A30); ``ref`` is ``None`` for one
    this tool never uploaded."""

    model_config = ConfigDict(frozen=True)

    video_id: int
    state: str | None = None
    ref: str | None = None
    thumbnail_url: str | None = None


class EtsyVideosSnapshot(BaseModel):
    """Both sides for the deploy review (A30). The live side comes in Etsy's
    response order, which says nothing about the gallery (decision 9)."""

    model_config = ConfigDict(frozen=True)

    desired: tuple[DesiredVideoSnapshot, ...]
    live: tuple[LiveVideoSnapshot, ...]


class EtsyVideosStage:
    name = "etsy_videos"
    local = False
    group: str | None = "etsy_media"
    applied_model = AppliedEtsyVideos

    def desired(
        self, ctx: RunContext, listing: str, applied: AppliedEtsyVideos | None
    ) -> EtsyVideosDesired | Blocked:
        workspace = ctx.workspace
        config = workspace.load_listing(listing)
        listing_dir = workspace.listing_dir(listing)
        # A listing that has never had a video asks nothing of Etsy, so it
        # is not refused for want of a shop it would never use.
        if not any(media_kind(e) == "video" for e in config.media) and not (
            applied is not None and applied.videos
        ):
            return EtsyVideosDesired(videos=())
        blocked = check_etsy_shop(ctx, consequence=NO_SHOP_CONSEQUENCE) or check_videos(
            WorkspaceFacts.for_files(workspace).videos(config, listing_dir)
        )
        if blocked is not None:
            return blocked

        videos: list[DesiredVideo] = []
        images_before = 0
        for entry in config.media:
            if media_kind(entry) == "image":
                images_before += 1
                continue
            assert isinstance(entry, str)  # noqa: S101 - a template entry is always an image
            source = workspace.resolve_ref(entry, listing_dir=listing_dir)
            videos.append(
                DesiredVideo(
                    ref=entry,
                    source=source,
                    content_hash=hash_file(source),
                    file=to_workspace_relative_posix(workspace.root, source),
                    # The featured video's place is fixed; only the second
                    # has an anchor, the images before it (decision 9).
                    after_images=images_before if videos else None,
                )
            )
        return EtsyVideosDesired(
            videos=tuple(videos),
            image_refs=tuple(manifest_ref(e) for e in config.media if media_kind(e) == "image"),
            swatches=tuple(swatch_refs(config.media, config.etsy.variation_images).items()),
            colours=tuple(config.colors),
        )

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: AppliedEtsyVideos | None
    ) -> EtsyVideosLive | None:
        """`getListing?includes=Videos`, split into ours and foreign by
        ``etsy_video_ids``. ``None`` without a request before `publish` has
        minted a listing."""
        del applied
        listing_id = etsy_listing_id(lock)
        if listing_id is None:
            return None
        live = ctx.require_etsy().get_listing(listing_id, include_videos=True)
        if live is None:
            return None
        known: dict[str, int] = dict(lock.remote.get(VIDEO_IDS_KEY) or {})
        ref_by_id = {video_id: ref for ref, video_id in known.items()}
        listed = {video.video_id for video in live.videos}
        return EtsyVideosLive(
            videos=tuple(
                LiveVideo(
                    video_id=video.video_id,
                    state=video.video_state,
                    ref=ref_by_id.get(video.video_id),
                    thumbnail_url=video.thumbnail_url,
                )
                for video in live.videos
            ),
            missing_refs=tuple(ref for ref, video_id in known.items() if video_id not in listed),
        )

    def plan(
        self,
        desired: EtsyVideosDesired,
        applied: AppliedEtsyVideos | None,
        live: EtsyVideosLive | None,
    ) -> Verdict:
        wanted = desired.applied()
        drift = _drift(applied, live)
        if applied is None:
            if not wanted.videos:
                return Verdict.no_work()
            return Verdict.work(
                f"{len(wanted.videos)} video(s), never uploaded",
                changes=_changes(wanted, None),
                actions=_actions(desired),
            )
        if wanted != applied:
            return Verdict.work(
                "the videos in media: changed",
                changes=_changes(wanted, applied),
                actions=_actions(desired),
                drift=drift,
            )
        if drift:
            return Verdict.work(
                "one of our videos is missing or inactive on Etsy -- uploading it again",
                actions=_actions(desired),
                drift=drift,
            )
        return Verdict.no_work()

    def snapshot(
        self, desired: EtsyVideosDesired, live: EtsyVideosLive | None
    ) -> EtsyVideosSnapshot:
        return EtsyVideosSnapshot(
            desired=tuple(
                DesiredVideoSnapshot(ref=v.ref, file=v.file, after_images=v.after_images)
                for v in desired.videos
            ),
            live=tuple(
                LiveVideoSnapshot(
                    video_id=v.video_id, state=v.state, ref=v.ref, thumbnail_url=v.thumbnail_url
                )
                for v in (live.videos if live is not None else ())
            ),
        )

    def apply(
        self,
        ctx: RunContext,
        desired: EtsyVideosDesired,
        applied: AppliedEtsyVideos | None,
        live: EtsyVideosLive | None,
        lock: Lockfile,
    ) -> StageApplyResult:
        placer = _Placer(
            ctx,
            ctx.require_etsy(),
            shop_id=ctx.workspace.defaults.etsy.require_shop_id(),
            listing_id=require_etsy_listing_id(lock, to="place videos"),
            known=dict(lock.remote.get(VIDEO_IDS_KEY) or {}),
            applied=applied,
            live=live,
        )
        wanted = {video.ref for video in desired.videos}
        placer.sweep(keep=wanted)

        featured, *rest = desired.videos or (None,)
        second = rest[0] if rest else None
        moved = False
        if featured is not None:
            if placer.placed(featured, slot=0):
                placer.keep(featured)
            else:
                placer.remove_all()
                placer.attach(featured)
                moved = True
        if second is not None:
            if not moved and placer.placed(second, slot=1):
                placer.keep(second)
            else:
                placer.place_after_images(second, desired, lock)

        return StageApplyResult(
            applied=AppliedEtsyVideos(
                videos=tuple(placer.sent[v.ref] for v in desired.videos)
            ).model_dump(mode="json"),
            remote={VIDEO_IDS_KEY: {v.ref: placer.ids[v.ref] for v in desired.videos}},
        )


class _Placer:
    """One apply's view of the listing's videos, kept current as it writes,
    so each step asks what is on the listing *now* rather than at plan time."""

    def __init__(
        self,
        ctx: RunContext,
        client: EtsyListingClient,
        *,
        shop_id: int,
        listing_id: int,
        known: dict[str, int],
        applied: AppliedEtsyVideos | None,
        live: EtsyVideosLive | None,
    ) -> None:
        self._ctx = ctx
        self._client = client
        self._shop_id = shop_id
        self._listing_id = listing_id
        self._known = known
        self._applied = applied.videos if applied is not None else ()
        self._drifted = live.drifted_refs if live is not None else frozenset()
        self._on_listing: dict[int, LiveVideo] = {
            v.video_id: v for v in (live.videos if live is not None else ())
        }
        self.ids: dict[str, int] = {}
        self.sent: dict[str, AppliedVideo] = {}

    def sweep(self, *, keep: set[str]) -> None:
        """Step 1: everything that is not one of ours, active and wanted."""
        for video in list(self._on_listing.values()):
            if video.ref is None or video.state != "active" or video.ref not in keep:
                self._ctx.emit(f"removing video {video.ref or video.video_id}")
                self._delete(video.video_id)

    def placed(self, video: DesiredVideo, *, slot: int) -> bool:
        """Last applied in this slot with these bytes and anchor, and still
        active on the listing."""
        video_id = self._known.get(video.ref)
        return (
            slot < len(self._applied)
            and self._applied[slot] == video.applied()
            and video_id in self._on_listing
        )

    def keep(self, video: DesiredVideo) -> None:
        self.ids[video.ref] = self._known[video.ref]
        self.sent[video.ref] = video.applied()

    def remove_all(self) -> None:
        """Step 2's price: a surviving video would be promoted to featured."""
        for video_id in list(self._on_listing):
            self._delete(video_id)

    def attach(self, video: DesiredVideo) -> None:
        """Re-attach by id when Etsy already has these bytes from us;
        upload otherwise, and always for a drifted one."""
        current = hash_file(video.source)
        video_id = self._known.get(video.ref)
        previous = {v.ref: v.hash for v in self._applied}.get(video.ref)
        if video_id is not None and previous == current and video.ref not in self._drifted:
            self._ctx.emit(f"re-attaching {video.ref}")
            attached = self._client.attach_listing_video(self._shop_id, self._listing_id, video_id)
        else:
            self._ctx.emit(f"uploading {video.ref}")
            attached = self._client.upload_listing_video(
                self._shop_id,
                self._listing_id,
                file_name=video.source.name,
                contents=video.source.read_bytes(),
            )
        self._on_listing[attached.video_id] = LiveVideo(
            video_id=attached.video_id, state="active", ref=video.ref
        )
        self.ids[video.ref] = attached.video_id
        self.sent[video.ref] = AppliedVideo(
            ref=video.ref, hash=current, after_images=video.after_images
        )

    def place_after_images(
        self, video: DesiredVideo, desired: EtsyVideosDesired, lock: Lockfile
    ) -> None:
        """Step 3 and 4: anchored by the image count at attach time, so the
        listing is cut to that many for one attach, then restored."""
        video_id = self._known.get(video.ref)
        if video_id is not None and video_id in self._on_listing:
            self._delete(video_id)
        # `lock.remote` is threaded through the run (A26), so these are the
        # ids `etsy_media` set a moment ago in this same apply.
        image_ids_by_ref: dict[str, int] = dict(lock.remote.get(IMAGE_IDS_KEY) or {})
        image_ids = [image_ids_by_ref[r] for r in desired.image_refs if r in image_ids_by_ref]
        anchor = video.after_images or 0
        cut = anchor < len(image_ids)
        if cut:
            self._ctx.emit(f"showing only the first {anchor} image(s) while placing {video.ref}")
            self._set_image_ids(image_ids[:anchor])
        self.attach(video)
        if cut:
            self._set_image_ids(image_ids)
        if desired.swatches:
            set_variation_images(
                self._ctx,
                self._client,
                shop_id=self._shop_id,
                listing_id=self._listing_id,
                colours=desired.colours,
                image_id_by_colour={
                    colour: image_ids_by_ref[ref]
                    for colour, ref in desired.swatches
                    if ref in image_ids_by_ref
                },
            )

    def _set_image_ids(self, image_ids: list[int]) -> None:
        self._client.update_listing(self._shop_id, self._listing_id, {"image_ids": image_ids})

    def _delete(self, video_id: int) -> None:
        self._client.delete_listing_video(self._shop_id, self._listing_id, video_id)
        del self._on_listing[video_id]


def _changes(
    wanted: AppliedEtsyVideos, applied: AppliedEtsyVideos | None
) -> tuple[FieldChange, ...]:
    """What differs, per slot, with the ref itself as the value.

    A slot whose video changed is ``videos.featured``/``videos.second``,
    ref before and after, so a reader can tell a new video from one that only
    moved slot by the refs alone -- the deploy review's New and Removed badges
    come from here rather than from a comparison of its own (A2, PRD 72). The
    same ref with new bytes is ``.contents``, digest before and after; the
    second video moved among the images is ``.after_images``, its anchor
    before and after.
    """
    before_videos = applied.videos if applied is not None else ()
    changes: list[FieldChange] = []
    for slot, path in enumerate(("videos.featured", "videos.second")):
        after = wanted.videos[slot] if slot < len(wanted.videos) else None
        before = before_videos[slot] if slot < len(before_videos) else None
        if after == before:
            continue
        if after is None or before is None or after.ref != before.ref:
            changes.append(
                FieldChange(
                    path=path,
                    before=before.ref if before is not None else None,
                    after=after.ref if after is not None else None,
                )
            )
            continue
        if after.hash != before.hash:
            changes.append(
                FieldChange(
                    path=f"{path}.contents", before=_digest(before.hash), after=_digest(after.hash)
                )
            )
        if after.after_images != before.after_images:
            changes.append(
                FieldChange(
                    path=f"{path}.after_images",
                    before=before.after_images,
                    after=after.after_images,
                )
            )
    return tuple(changes)


def _digest(content_hash: str) -> str:
    """``sha256:`` and the first twelve hex digits: enough to tell two files
    apart in a plan, short enough to read."""
    return content_hash[: len("sha256:") + 12]


def _actions(desired: EtsyVideosDesired) -> tuple[Action, ...]:
    if not desired.videos:
        return (Action(description="remove this listing's videos from Etsy"),)
    return (
        Action(
            description=f"place {len(desired.videos)} video(s) in the gallery",
            inputs=tuple(v.file for v in desired.videos),
        ),
    )


def _drift(applied: AppliedEtsyVideos | None, live: EtsyVideosLive | None) -> tuple[Drift, ...]:
    if applied is None or live is None:
        return ()
    drifted = sorted(live.drifted_refs & {v.ref for v in applied.videos})
    if not drifted:
        return ()
    return (Drift(path="videos", last_applied=drifted, live="missing or inactive"),)
