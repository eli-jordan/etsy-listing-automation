import { MutedClip } from "../../components/MutedClip";
import { pictureFor, type SceneSource } from "../../media";
import type { RenderSnapshot } from "../../types";
import type {
  AfterImageTile,
  AfterVideoTile,
  BeforeImageTile,
  BeforeVideoTile,
  Comparison as ComparisonData,
  TagsBlock,
} from "./comparison";
import { wordDiff } from "./wordDiff";

/**
 * The centre of the page: "On Etsy now" / "After apply", or a single column
 * once there is nothing to compare or the run has applied (spec's
 * "Comparison" element, decision 3).
 *
 * Named `ComparisonView`, not `Comparison` -- the frontend module table
 * names this file `Comparison.tsx` beside the pure `comparison.ts` it
 * consumes, differing only in case. That collides on Windows and macOS's
 * default case-insensitive filesystems (this repo's own toolchain, per
 * CLAUDE.md's Environment section) and `tsc` refuses to build it even on a
 * case-sensitive one, having seen both spellings resolve to one path. One
 * of the two names had to move; the pure module keeps the plain noun.
 *
 * **Where a gallery tile's picture comes from** is the one place this
 * component adds a rule `comparison.ts` does not carry, because it needs
 * the DOM-facing side of `media.ts` `comparison.ts` is pure and must not
 * import:
 *
 * - "On Etsy now" prefers the live `url` (Etsy's own CDN image). A `ref`
 * with no `url` yet (freshly uploaded, or a hand-added Shop Manager image
 * this tool never uploaded) falls back to the local render the same way
 * the spec says to.
 * - "After apply" for a scene the render stage will re-render shows a
 * spinner until `previewsRendered` names it, then the preview endpoint's
 * own file. A scene whose render is already current (`state: "cached"`)
 * shows today's picture directly -- there is nothing new to wait for.
 * Neither of those endpoints exists for a bare shared-media ref, which
 * renders through `pictureFor` like the editor's own reel does.
 * - A video is drawn "after" from its own file, as a muted clip the
 * browser gives a poster frame, and "now" from Etsy's `thumbnail_url` --
 * the one picture of it the API offers.
 */

export interface ListingMediaContext {
  name: string;
  /** Where a cached scene's picture resolves its artwork from (A35), or
   * `null` to show the bare photo. */
  scene: SceneSource | null;
}

function parseRef(ref: string): { template: string; colour: string | null } | null {
  const colon = ref.indexOf(":");
  if (colon === -1) {
    // A bare template name (a `multiple`/`single`-kind scene has no colour
    // segment) reads as a template only when it isn't a shared-asset path --
    // the one distinction `_ref()` on the backend doesn't need to make,
    // because it already knows which case it is building.
    if (ref.includes("/") || ref.includes(".")) return null;
    return { template: ref, colour: null };
  }
  return { template: ref.slice(0, colon), colour: ref.slice(colon + 1) };
}

function sceneState(
  renderSnapshot: RenderSnapshot | null,
  template: string,
  colour: string | null,
) {
  return renderSnapshot?.scenes.find((s) => s.template === template && s.colour === colour) ?? null;
}

interface TileImage {
  src: string | null;
  /** The plan's preview of this scene is still rendering. */
  pending: boolean;
}

/** Where an after-apply tile's image comes from: the caller's own lookup,
 * the listing's picture for a plain file, or the scene -- its cached render,
 * or this plan's preview once that has rendered. */
function afterTileImage(
  ref: string,
  listing: ListingMediaContext,
  renderSnapshot: RenderSnapshot | null,
  previewsRendered: Set<string>,
  imageUrlForRef: ((ref: string) => string | null) | undefined,
): TileImage {
  if (imageUrlForRef !== undefined) return { src: imageUrlForRef(ref), pending: false };
  const parsed = parseRef(ref);
  if (parsed === null) {
    return { src: pictureFor(ref, listing.scene, "full", listing.name || null), pending: false };
  }
  const scene = sceneState(renderSnapshot, parsed.template, parsed.colour);
  const key = `${parsed.template}|${parsed.colour ?? ""}`;
  const ready =
    scene === null || scene.state === "cached" || scene.preview || previewsRendered.has(key);
  if (!ready) return { src: null, pending: true };
  if (scene !== null && scene.state !== "cached") {
    return {
      src: previewUrl(listing.name, parsed.template, parsed.colour, scene.scene_hash),
      pending: false,
    };
  }
  const picture = { template: parsed.template, colour: parsed.colour };
  return { src: pictureFor(picture, listing.scene, "full"), pending: false };
}

function AfterTile({
  tile,
  listing,
  renderSnapshot,
  previewsRendered,
  imageUrlForRef,
}: {
  tile: AfterImageTile;
  listing: ListingMediaContext;
  renderSnapshot: RenderSnapshot | null;
  previewsRendered: Set<string>;
  imageUrlForRef: ((ref: string) => string | null) | undefined;
}) {
  const { src, pending } = afterTileImage(
    tile.ref,
    listing,
    renderSnapshot,
    previewsRendered,
    imageUrlForRef,
  );

  return (
    <figure className="dv-thumb-wrap">
      <div
        className={`dv-thumb${tile.badge === "new" ? " dv-thumb--new" : ""}${tile.replaced ? " dv-thumb--replaced" : ""}`}
        title={tile.replaced ? "Changed" : undefined}
      >
        {pending ? (
          <span className="dv-spinner" aria-hidden="true" />
        ) : (
          <img alt={tile.ref} src={src ?? undefined} />
        )}
        {tile.badge === "new" && <span className="dv-thumb__badge dv-thumb__badge--new">New</span>}
        {tile.badge === "moved" && (
          <span className="dv-thumb__badge dv-thumb__badge--moved">was {tile.movedFrom}</span>
        )}
      </div>
    </figure>
  );
}

/** This plan's own preview of the scene, named by the hash the plan computed
 * for it -- a file read, where asking without the hash re-plans the listing. */
function previewUrl(
  listing: string,
  template: string,
  colour: string | null,
  sceneHash: string,
): string {
  const base = `/api/listings/${encodeURIComponent(listing)}/previews/${encodeURIComponent(template)}`;
  const path = colour !== null ? `${base}/${encodeURIComponent(colour)}` : base;
  return `${path}?hash=${encodeURIComponent(sceneHash)}`;
}

function BeforeTile({ tile }: { tile: BeforeImageTile }) {
  return (
    <figure className="dv-thumb-wrap">
      <div
        className={`dv-thumb${tile.badge === "removed" ? " dv-thumb--gone" : ""}${tile.replaced ? " dv-thumb--replaced" : ""}`}
        title={tile.replaced ? "Changed" : undefined}
      >
        {tile.url !== null ? (
          <img alt={tile.ref ?? "listing image"} src={tile.url} />
        ) : (
          <span className="dv-thumb--empty" aria-hidden="true" />
        )}
        {tile.badge === "removed" && (
          <span className="dv-thumb__badge dv-thumb__badge--gone">Removed</span>
        )}
      </div>
    </figure>
  );
}

function AfterVideo({ tile, listing }: { tile: AfterVideoTile; listing: string }) {
  const isNew = tile.badge === "new";
  return (
    <figure className="dv-thumb-wrap">
      <div className={`dv-thumb${isNew ? " dv-thumb--new" : ""}`}>
        <MutedClip src={pictureFor(tile.ref, null, "full", listing || null)} label={tile.ref} />
        {isNew && <span className="dv-thumb__badge dv-thumb__badge--new">New</span>}
      </div>
      <figcaption className="dv-thumb__caption">
        {tile.slot === "featured" ? "Featured · 2nd" : `After ${tile.afterImages ?? 0} images`}
      </figcaption>
    </figure>
  );
}

function BeforeVideo({ tile }: { tile: BeforeVideoTile }) {
  const gone = tile.badge === "removed";
  return (
    <figure className="dv-thumb-wrap">
      <div className={`dv-thumb${gone ? " dv-thumb--gone" : ""}`}>
        {tile.url !== null ? (
          <img alt={tile.ref ?? "listing video"} src={tile.url} />
        ) : (
          <span className="dv-thumb--empty" aria-hidden="true" />
        )}
        {gone && <span className="dv-thumb__badge dv-thumb__badge--gone">Removed</span>}
      </div>
      <figcaption className="dv-thumb__caption">
        {tile.ref === null ? "Not uploaded by this tool" : tile.ref.split("/").pop()}
        {tile.inactive && " · Not playing on Etsy"}
      </figcaption>
    </figure>
  );
}

function Block({
  label,
  changed,
  side,
  children,
}: {
  label: string;
  changed: boolean;
  side: "before" | "after";
  children: React.ReactNode;
}) {
  const cls = changed ? `dv-block dv-block--${side}` : "dv-block";
  return (
    <div className={cls}>
      <div className="dv-block__label">
        <span className="dv-eyebrow">{label}</span>
        {changed && (
          <span className={side === "before" ? "dv-changed dv-changed--before" : "dv-changed"}>
            {side === "after" ? "Changes" : "Replaced"}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function StringList({
  label,
  block,
  side,
}: {
  label: string;
  block: TagsBlock;
  side: "before" | "after";
}) {
  const isAfter = side === "after";
  return (
    <Block label={label} changed={block.changed} side={side}>
      <div className="dv-chips">
        {(isAfter ? block.after : block.before).map((value) => {
          const added = isAfter && block.added.includes(value);
          const removed = !isAfter && block.removed.includes(value);
          return (
            <span
              key={value}
              className={`dv-chip${added ? " dv-chip--add" : ""}${removed ? " dv-chip--rm" : ""}`}
            >
              {value}
            </span>
          );
        })}
      </div>
    </Block>
  );
}

/** A text field on one side: the word diff after a change, the plain
 * value otherwise, and a dash for nothing on Etsy yet. */
function TextDiff({
  field,
  isAfter,
}: {
  field: { before: string | null; after: string; changed: boolean };
  isAfter: boolean;
}) {
  if (!isAfter) return field.before ?? "—";
  if (!field.changed) return field.after;
  return wordDiff(field.before ?? "", field.after).map((token, index) => (
    <span key={index} className={token.type === "same" ? undefined : `dv-${token.type}`}>
      {token.text}{" "}
    </span>
  ));
}

function Column({
  side,
  comparison,
  listing,
  renderSnapshot,
  previewsRendered,
  etsyListingIdLabel,
  imageUrlForRef,
}: {
  side: "before" | "after";
  comparison: ComparisonData;
  listing: ListingMediaContext;
  renderSnapshot: RenderSnapshot | null;
  previewsRendered: Set<string>;
  etsyListingIdLabel: string;
  imageUrlForRef: ((ref: string) => string | null) | undefined;
}) {
  const isAfter = side === "after";
  const { title, description, tags, materials, colours, price, images, videos } = comparison;

  return (
    <div className="dv-col">
      <div className="dv-col__head">
        <h3>{isAfter ? "After apply" : "On Etsy now"}</h3>
        <span className="dv-eyebrow">{isAfter ? "from this plan" : etsyListingIdLabel}</span>
      </div>

      {images && (
        <Block label="Images" changed={images.changed} side={side}>
          <div className="dv-gallery">
            {isAfter
              ? images.after.map((tile) => (
                  <AfterTile
                    key={tile.rank}
                    tile={tile}
                    listing={listing}
                    renderSnapshot={renderSnapshot}
                    previewsRendered={previewsRendered}
                    imageUrlForRef={imageUrlForRef}
                  />
                ))
              : images.before.map((tile) => <BeforeTile key={tile.rank} tile={tile} />)}
          </div>
        </Block>
      )}

      {videos && (
        <Block label="Videos" changed={videos.changed} side={side}>
          <div className="dv-gallery dv-gallery--videos">
            {isAfter
              ? videos.after.map((tile) => (
                  <AfterVideo key={tile.ref} tile={tile} listing={listing.name} />
                ))
              : videos.before.map((tile) => <BeforeVideo key={tile.videoId} tile={tile} />)}
          </div>
        </Block>
      )}

      {title && (
        <Block label="Title" changed={title.changed} side={side}>
          <div className="dv-title">
            <TextDiff field={title} isAfter={isAfter} />
          </div>
        </Block>
      )}

      {description && (
        <Block label="Description" changed={description.changed} side={side}>
          <div className="dv-description">
            <TextDiff field={description} isAfter={isAfter} />
          </div>
        </Block>
      )}

      {price && (
        <Block label="Price" changed={price.changed} side={side}>
          <div className="dv-price dv-tnum">
            {formatRange(isAfter ? price.after : price.before)}
          </div>
        </Block>
      )}

      {colours && (
        <Block label="Colours" changed={colours.changed} side={side}>
          <div className="dv-swatches">
            {(isAfter ? colours.after : colours.before).map((colour) => {
              const isNew = isAfter && colours.added.includes(colour);
              return (
                <span key={colour} className={isNew ? "dv-sw dv-sw--new" : "dv-sw"}>
                  {colour}
                  {isNew && " · new"}
                </span>
              );
            })}
          </div>
        </Block>
      )}

      {tags && <StringList label="Tags" block={tags} side={side} />}
      {materials && <StringList label="Materials" block={materials} side={side} />}
    </div>
  );
}

/** `"349 NOK"` alone, or `"349–399 NOK"` -- the bare low amount, an
 * en-dash, then the high amount with its unit, matching how the design mock
 * reads a price range. */
function formatRange(range: { min: string; max: string } | null): string {
  if (range === null) return "—";
  if (range.min === range.max) return range.min;
  const minAmount = range.min.split(" ")[0] ?? range.min;
  return `${minAmount}–${range.max}`;
}

export function ComparisonView({
  comparison,
  listing,
  renderSnapshot,
  previewsRendered,
  collapsed,
  etsyListingId,
  imageUrlForRef,
}: {
  comparison: ComparisonData;
  listing: ListingMediaContext;
  renderSnapshot: RenderSnapshot | null;
  previewsRendered: Set<string>;
  /** Collapse to one "On Etsy now" column -- once applied, or when the plan
   * found nothing to compare. */
  collapsed: boolean;
  etsyListingId: number | null;
  /** Optional fixture resolver for canvases and component galleries. The app
   * normally derives these URLs from the listing's media refs. */
  imageUrlForRef?: (ref: string) => string | null;
}) {
  const etsyListingIdLabel = etsyListingId !== null ? `listing ${etsyListingId}` : "";
  const columnProps = {
    comparison,
    listing,
    renderSnapshot,
    previewsRendered,
    etsyListingIdLabel,
    imageUrlForRef,
  };

  if (!comparison.hasEtsyListing) {
    return (
      <div className="dv-compare dv-compare--single">
        <Column {...columnProps} side="after" />
        <p className="dv-note">Not on Etsy yet.</p>
      </div>
    );
  }

  if (collapsed) {
    return (
      <div className="dv-compare dv-compare--single">
        <Column {...columnProps} side="before" />
      </div>
    );
  }

  return (
    <div className="dv-compare">
      <Column {...columnProps} side="before" />
      <Column {...columnProps} side="after" />
    </div>
  );
}
