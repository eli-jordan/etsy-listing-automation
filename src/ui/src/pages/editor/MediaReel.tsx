import { ArrowLeftIcon } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { ArrowRightIcon } from "@phosphor-icons/react/dist/csr/ArrowRight";
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useState } from "react";
import { MutedClip } from "../../components/MutedClip";
import { useHoverPlay } from "../../hooks/useHoverPlay";
import { useIsPhone } from "../../phone/usePhone";
import { type Artwork, type MediaOwner, mediaKind, mediaLabel, pictureFor } from "../../media";
import type { MediaFileSummary, MediaEntry } from "../../types";
import { MAX_IMAGES, MAX_VIDEOS, canReorder } from "./mediaEdits";
import type { Focus } from "./focus";
import { PositionGlyph } from "./positions/PositionControls";

/**
 * The listing's gallery, in the order Etsy will show it, reorderable by drag.
 *
 * Videos sit inline, because `media:` is the gallery: a muted clip
 * on its own frame with a play badge, playing on hover. Position 2 is where
 * Etsy pins the featured video, and is labelled so. Which drops the gallery
 * rules allow is `mediaEdits`' answer, asked while a tile is carried so a
 * refused target looks refused; a drop there changes nothing and the tile
 * snaps back.
 *
 * The order is a product decision, not a display detail -- the first tile is
 * the Etsy thumbnail -- so the drag is what this module is *for*, and the
 * drag's own state (which tile is being carried, which one it is over) lives
 * here and nowhere else. It used to sit in the tab alongside eleven other
 * pieces of state, which is how "remove a tile" and "open the carousel" came
 * to share one click handler.
 */

interface Props {
  media: readonly MediaEntry[];
  scene: Artwork | null;
  swatchTemplate: string | null;
  selectedIndex: number | null;
  /** Whose `./` refs these are -- a listing (by name) or a listing
   * template -- or `null` for a draft. */
  listing: MediaOwner | string | null;
  /** Every file the locator lists, both groups -- what a file ref's tile
   * points the preview at. */
  files: readonly MediaFileSummary[];
  onRemove: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onFocus: (focus: Focus) => void;
  positioned?: ReadonlySet<string>;
  /** Opens Add media, when the reel carries the button for it: on a phone,
   * where the locator is a sheet rather than a column beside the reel. */
  onAdd?: () => void;
  /** On a phone: the selected tile's bar opens it full size, and a second
   * tap on the tile, the bar's ×, or Escape lets go of it. */
  onView?: (index: number) => void;
  onDeselect?: () => void;
  /** On a phone, when the selected tile is a template whose design this
   * listing can position: the bar's Adjust opens the preview to do it in. */
  onAdjust?: () => void;
}

export function MediaReel({
  media,
  scene,
  swatchTemplate,
  selectedIndex,
  listing,
  files,
  onRemove,
  onReorder,
  onFocus,
  positioned,
  onAdd,
  onView,
  onDeselect,
  onAdjust,
}: Props) {
  const phone = useIsPhone();
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const images = media.filter((entry) => mediaKind(entry) === "image").length;
  const videos = media.length - images;

  function focusFor(entry: MediaEntry) {
    if (typeof entry !== "string") {
      onFocus({ kind: "template", template: entry.template, colour: entry.colour ?? null });
      return;
    }
    // Only a file still on disk can be previewed; a ref whose file has gone
    // keeps its tile and its label, which is how the user finds out it is
    // missing.
    const asset = files.find((a) => a.ref === entry);
    if (asset !== undefined) onFocus({ kind: "file", asset });
  }

  return (
    <div className="reel">
      <div className="reel__head">
        <span className="reel__title">Listing gallery</span>
        <span className="reel__count">
          {images} of {MAX_IMAGES} images
        </span>
        <span className="reel__count">
          {videos} of {MAX_VIDEOS} videos
        </span>
        <span className="reel__hint">{reelHint(images, phone)}</span>
        {onAdd !== undefined && (
          <button type="button" className="btn btn-primary reel__add" onClick={onAdd}>
            <PlusIcon weight="bold" aria-hidden="true" />
            Add media
          </button>
        )}
      </div>
      <div className="reel__track">
        {media.map((entry, index) => {
          const over = dragIndex !== null && dragIndex !== index && dragOverIndex === index;
          return (
            <ReelTile
              key={`${mediaLabel(entry)}-${index}`}
              entry={entry}
              index={index}
              picture={pictureFor(entry, scene, "tile", listing)}
              suppliesSwatch={
                typeof entry !== "string" &&
                swatchTemplate !== null &&
                entry.template === swatchTemplate &&
                entry.colour !== null
              }
              positioned={typeof entry !== "string" && (positioned?.has(entry.template) ?? false)}
              state={[
                selectedIndex === index ? "rtile--selected" : "",
                dragIndex === index ? "rtile--dragging" : "",
                over && canReorder(media, dragIndex, index) ? "rtile--over" : "",
                over && !canReorder(media, dragIndex, index) ? "rtile--refused" : "",
              ]}
              onDragStart={() => setDragIndex(index)}
              onDragOver={() => setDragOverIndex(index)}
              onDrop={() => {
                if (dragIndex !== null) onReorder(dragIndex, index);
                setDragIndex(null);
                setDragOverIndex(null);
              }}
              onDragEnd={() => {
                setDragIndex(null);
                setDragOverIndex(null);
              }}
              onFocus={() =>
                selectedIndex === index && onDeselect !== undefined ? onDeselect() : focusFor(entry)
              }
              onRemove={() => onRemove(index)}
            />
          );
        })}
        {media.length === 0 && (
          <p className="reel__empty">
            {phone
              ? "Nothing here yet — tap Add media to add a mockup template."
              : "Nothing here yet — add a mockup template from the left."}
          </p>
        )}
      </div>
      {phone && selectedIndex !== null && media[selectedIndex] !== undefined && (
        <ReelMoves
          media={media}
          index={selectedIndex}
          onReorder={onReorder}
          onRemove={onRemove}
          onView={onView}
          onAdjust={onAdjust}
          onDone={onDeselect}
        />
      )}
    </div>
  );
}

function reelHint(images: number, phone: boolean): string {
  if (images >= MAX_IMAGES) {
    return `At Etsy's ${MAX_IMAGES}-image limit — remove one before adding another`;
  }
  return phone
    ? "Tap an image to view, adjust, move or remove it"
    : "Drag a tile to change the order Etsy shows them in";
}

/**
 * The phone's way to reorder: only some phone browsers let a finger carry a
 * tile, after a long press, so the selected tile gets a bar under the reel
 * that moves it one place at a time, or straight to the front, under the
 * same gallery rules a drop obeys. The selection follows the tile, so
 * repeated taps keep moving the same one.
 *
 * The bar is also the tile's way to the larger views: View opens it full
 * size, and Adjust -- for a template this listing positions its design on --
 * opens the preview with Position mode. It lets go of the tile on ×, or
 * Escape.
 */
function ReelMoves({
  media,
  index,
  onReorder,
  onRemove,
  onView,
  onAdjust,
  onDone,
}: {
  media: readonly MediaEntry[];
  index: number;
  onReorder: (from: number, to: number) => void;
  onRemove: (index: number) => void;
  onView: ((index: number) => void) | undefined;
  onAdjust: (() => void) | undefined;
  onDone: (() => void) | undefined;
}) {
  const entry = media[index] as MediaEntry;
  const label = mediaLabel(entry);
  const video = mediaKind(entry) === "video";
  const move = (to: number) => (canReorder(media, index, to) ? () => onReorder(index, to) : null);
  const earlier = index > 0 ? move(index - 1) : null;
  const later = index < media.length - 1 ? move(index + 1) : null;
  const first = index === 0 ? null : move(0);
  const stuck = earlier === null && later === null && first === null;
  useEscape(onDone);
  return (
    <div className="reel-moves" role="group" aria-label={`Move ${label}`}>
      <div className="reel-moves__head">
        <span className="reel-moves__what">
          {`${video ? "Video" : "Image"} ${index + 1}: `}
          <strong>{label}</strong>
        </span>
        {onView !== undefined && (
          <button type="button" className="btn btn-ghost" onClick={() => onView(index)}>
            View
          </button>
        )}
        {onAdjust !== undefined && (
          <button type="button" className="btn btn-ghost" onClick={onAdjust}>
            Adjust
          </button>
        )}
        {onDone !== undefined && (
          <button
            type="button"
            className="btn btn-ghost reel-moves__done"
            aria-label="Done"
            onClick={onDone}
          >
            <XIcon aria-hidden="true" />
          </button>
        )}
      </div>
      {video && stuck && (
        <span className="reel-moves__why">
          Etsy shows a listing&rsquo;s video second, so it stays in that place
        </span>
      )}
      <div className="reel-moves__buttons">
        <button
          type="button"
          className="btn btn-ghost"
          aria-label="Move earlier"
          disabled={earlier === null}
          onClick={earlier ?? undefined}
        >
          <ArrowLeftIcon aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          aria-label="Move later"
          disabled={later === null}
          onClick={later ?? undefined}
        >
          <ArrowRightIcon aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={first === null}
          onClick={first ?? undefined}
        >
          Make thumbnail
        </button>
        <button
          type="button"
          className="btn btn-ghost reel-moves__remove"
          aria-label={`Remove ${label}`}
          onClick={() => onRemove(index)}
        >
          <TrashIcon aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

/** Escape lets go of the selected tile -- unless it is closing the full-size
 * view, Adjust's screen or a sheet over it, which have their own Escape. */
function useEscape(onDone: (() => void) | undefined) {
  useEffect(() => {
    if (onDone === undefined) return;
    const onKey = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        document.querySelector(".lightbox, .phone-screen, .modal-root") !== null
      ) {
        return;
      }
      onDone();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onDone]);
}

interface TileProps {
  entry: MediaEntry;
  index: number;
  picture: string;
  suppliesSwatch: boolean;
  positioned: boolean;
  state: string[];
  onDragStart: () => void;
  onDragOver: () => void;
  onDrop: () => void;
  onDragEnd: () => void;
  onFocus: () => void;
  onRemove: () => void;
}

function ReelTile({
  entry,
  index,
  picture,
  suppliesSwatch,
  positioned,
  state,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onFocus,
  onRemove,
}: TileProps) {
  const { ref: clipRef, play, rest } = useHoverPlay();
  const isVideo = mediaKind(entry) === "video";
  const label = mediaLabel(entry);
  return (
    <div
      className={["rtile", ...state].filter(Boolean).join(" ")}
      draggable
      onDragStart={(event) => {
        // A plain-text payload (Firefox starts no drag without one) and a
        // move, so nothing reads the tile as a picture or a link to open. A
        // synthetic drag has no `dataTransfer`.
        const carried = event.dataTransfer as DataTransfer | null | undefined;
        if (carried) {
          carried.effectAllowed = "move";
          carried.setData("text/plain", label);
        }
        onDragStart();
      }}
      onDragOver={(event) => {
        event.preventDefault();
        onDragOver();
      }}
      onDrop={(event) => {
        // The drop is the reorder's, not the browser's: left to it, the
        // browser opens what was dropped -- on a phone, the tile's small
        // picture, alone on the page in place of the editor.
        event.preventDefault();
        onDrop();
      }}
      onDragEnd={onDragEnd}
    >
      <div
        className="rtile__face"
        // A click, not a hover, points the preview here: the pointer crosses
        // the reel on its way to anything below it, and every tile it passed
        // used to swap the stage's picture and start another full render.
        onClick={onFocus}
        onMouseEnter={isVideo ? play : undefined}
        onMouseLeave={isVideo ? rest : undefined}
      >
        {isVideo ? (
          <>
            <MutedClip src={picture} clipRef={clipRef} label={label} />
            <span className="rtile__play" aria-hidden="true">
              ▶
            </span>
          </>
        ) : (
          // Not draggable itself, so a drag carries the tile, not the picture.
          <img src={picture} alt={label} loading="lazy" draggable={false} />
        )}
        <span className="rtile__pos">{index + 1}</span>
        {suppliesSwatch && (
          <span className="rtile__swatch" title="Supplies this colour's Etsy swatch">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2l10 10-10 10L2 12z" />
            </svg>
          </span>
        )}
        {positioned && (
          <span
            className="tp-tile-badge"
            title="This listing positions the design on this template"
          >
            <PositionGlyph />
          </span>
        )}
        <span
          className="rtile__x"
          role="button"
          aria-label={`Remove ${label}`}
          // The × sits inside the face, which points the preview at it -- so
          // removing a tile must not also preview the one that slid into its
          // place.
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        >
          ×
        </span>
        {index === 0 && <span className="rtile__first">Etsy thumbnail</span>}
        {index === 1 && isVideo && (
          <span className="rtile__first rtile__first--featured">Featured · shown 2nd</span>
        )}
      </div>
      <span className="rtile__label">{label}</span>
    </div>
  );
}
