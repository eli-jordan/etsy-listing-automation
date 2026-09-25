import { pictureFor, singleDesignName } from "../../media";
import type { ListingDetail, RenderSnapshot } from "../../types";
import type { AfterImageTile, BeforeImageTile, Comparison as ComparisonData } from "./comparison";
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
 *   with no `url` yet (freshly uploaded, or a hand-added Shop Manager image
 *   this tool never uploaded) falls back to the local render the same way
 *   the spec says to.
 * - "After apply" for a scene the render stage will re-render shows a
 *   spinner until `previewsRendered` names it, then the preview endpoint's
 *   own file. A scene whose render is already current (`state: "cached"`)
 *   shows today's picture directly -- there is nothing new to wait for.
 *   Neither of those endpoints exists for a bare shared-media ref, which
 *   renders through `pictureFor` like the editor's own reel does.
 */

export interface ListingMediaContext {
  name: string;
  design: ListingDetail["design"];
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
  const parsed = parseRef(tile.ref);
  const design = singleDesignName(listing.design);
  let src: string | null = null;
  let pending = false;

  if (imageUrlForRef !== undefined) {
    src = imageUrlForRef(tile.ref);
  } else if (parsed === null) {
    src = pictureFor(tile.ref, design, "full", listing.name || null);
  } else {
    const scene = sceneState(renderSnapshot, parsed.template, parsed.colour);
    const key = `${parsed.template}|${parsed.colour ?? ""}`;
    const ready =
      scene === null || scene.state === "cached" || scene.preview || previewsRendered.has(key);
    if (ready) {
      src =
        scene !== null && scene.state !== "cached"
          ? previewUrl(listing.name, parsed.template, parsed.colour)
          : pictureFor({ template: parsed.template, colour: parsed.colour }, design, "full");
    } else {
      pending = true;
    }
  }

  return (
    <figure className="dv-thumb-wrap">
      <div className={`dv-thumb${tile.badge === "new" ? " dv-thumb--new" : ""}`}>
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

function previewUrl(listing: string, template: string, colour: string | null): string {
  const base = `/api/listings/${encodeURIComponent(listing)}/previews/${encodeURIComponent(template)}`;
  return colour !== null ? `${base}/${encodeURIComponent(colour)}` : base;
}

function BeforeTile({ tile }: { tile: BeforeImageTile }) {
  return (
    <figure className="dv-thumb-wrap">
      <div className={`dv-thumb${tile.badge === "removed" ? " dv-thumb--gone" : ""}`}>
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
  const { title, description, tags, materials, colours, price, images } = comparison;

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

      {title && (
        <Block label="Title" changed={title.changed} side={side}>
          <div className="dv-title">
            {isAfter && title.changed
              ? wordDiff(title.before ?? "", title.after).map((token, index) => (
                  <span
                    key={index}
                    className={token.type === "same" ? undefined : `dv-${token.type}`}
                  >
                    {token.text}{" "}
                  </span>
                ))
              : isAfter
                ? title.after
                : (title.before ?? "—")}
          </div>
        </Block>
      )}

      {description && (
        <Block label="Description" changed={description.changed} side={side}>
          <div className="dv-description">
            {isAfter && description.changed
              ? wordDiff(description.before ?? "", description.after).map((token, index) => (
                  <span
                    key={index}
                    className={token.type === "same" ? undefined : `dv-${token.type}`}
                  >
                    {token.text}{" "}
                  </span>
                ))
              : isAfter
                ? description.after
                : (description.before ?? "—")}
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

      {tags && (
        <Block label="Tags" changed={tags.changed} side={side}>
          <div className="dv-chips">
            {(isAfter ? tags.after : tags.before).map((tag) => {
              const added = isAfter && tags.added.includes(tag);
              const removed = !isAfter && tags.removed.includes(tag);
              return (
                <span
                  key={tag}
                  className={`dv-chip${added ? " dv-chip--add" : ""}${removed ? " dv-chip--rm" : ""}`}
                >
                  {tag}
                </span>
              );
            })}
          </div>
        </Block>
      )}

      {materials && (
        <Block label="Materials" changed={materials.changed} side={side}>
          <div className="dv-chips">
            {(isAfter ? materials.after : materials.before).map((material) => {
              const added = isAfter && materials.added.includes(material);
              const removed = !isAfter && materials.removed.includes(material);
              return (
                <span
                  key={material}
                  className={`dv-chip${added ? " dv-chip--add" : ""}${removed ? " dv-chip--rm" : ""}`}
                >
                  {material}
                </span>
              );
            })}
          </div>
        </Block>
      )}
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

  if (!comparison.hasEtsyListing) {
    return (
      <div className="dv-compare dv-compare--single">
        <Column
          side="after"
          comparison={comparison}
          listing={listing}
          renderSnapshot={renderSnapshot}
          previewsRendered={previewsRendered}
          etsyListingIdLabel={etsyListingIdLabel}
          imageUrlForRef={imageUrlForRef}
        />
        <p className="dv-note">Not on Etsy yet.</p>
      </div>
    );
  }

  if (collapsed) {
    return (
      <div className="dv-compare dv-compare--single">
        <Column
          side="before"
          comparison={comparison}
          listing={listing}
          renderSnapshot={renderSnapshot}
          previewsRendered={previewsRendered}
          etsyListingIdLabel={etsyListingIdLabel}
          imageUrlForRef={imageUrlForRef}
        />
      </div>
    );
  }

  return (
    <div className="dv-compare">
      <Column
        side="before"
        comparison={comparison}
        listing={listing}
        renderSnapshot={renderSnapshot}
        previewsRendered={previewsRendered}
        etsyListingIdLabel={etsyListingIdLabel}
        imageUrlForRef={imageUrlForRef}
      />
      <Column
        side="after"
        comparison={comparison}
        listing={listing}
        renderSnapshot={renderSnapshot}
        previewsRendered={previewsRendered}
        etsyListingIdLabel={etsyListingIdLabel}
        imageUrlForRef={imageUrlForRef}
      />
    </div>
  );
}
