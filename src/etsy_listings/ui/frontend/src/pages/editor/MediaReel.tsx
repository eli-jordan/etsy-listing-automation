import { useState } from "react";
import { MutedClip } from "../../components/MutedClip";
import { useHoverPlay } from "../../hooks/useHoverPlay";
import { mediaKind, mediaLabel, pictureFor } from "../../media";
import type { MediaFileSummary, MediaEntry } from "../../types";
import { MAX_IMAGES, MAX_VIDEOS, canReorder } from "./mediaEdits";
import type { Focus } from "./focus";

/**
 * The listing's gallery, in the order Etsy will show it, reorderable by drag.
 *
 * Videos sit inline, because `media:` is the gallery (PRD 71): a muted clip
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
  design: string | null;
  swatchTemplate: string | null;
  selectedIndex: number | null;
  /** The listing a `./` ref belongs to, or `null` for a draft. */
  listing: string | null;
  /** Every file the locator lists, both groups -- what a file ref's tile
   * points the preview at. */
  files: readonly MediaFileSummary[];
  onOpen: (index: number) => void;
  onRemove: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onFocus: (focus: Focus) => void;
}

export function MediaReel({
  media,
  design,
  swatchTemplate,
  selectedIndex,
  listing,
  files,
  onOpen,
  onRemove,
  onReorder,
  onFocus,
}: Props) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  // Images are what Etsy caps at twenty; videos are counted apart (PRD 71).
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
        <span className="reel__hint">
          {images >= MAX_IMAGES
            ? `At Etsy's ${MAX_IMAGES}-image limit — remove one before adding another`
            : "Drag a tile to change the order Etsy shows them in"}
        </span>
      </div>
      <div className="reel__track">
        {media.map((entry, index) => {
          const over = dragIndex !== null && dragIndex !== index && dragOverIndex === index;
          return (
            <ReelTile
              key={`${mediaLabel(entry)}-${index}`}
              entry={entry}
              index={index}
              picture={pictureFor(entry, design, "tile", listing)}
              suppliesSwatch={
                typeof entry !== "string" &&
                swatchTemplate !== null &&
                entry.template === swatchTemplate &&
                entry.colour !== null
              }
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
              onOpen={() => onOpen(index)}
              onFocus={() => focusFor(entry)}
              onRemove={() => onRemove(index)}
            />
          );
        })}
        {media.length === 0 && (
          <p className="reel__empty">Nothing here yet — add a mockup template from the left.</p>
        )}
      </div>
    </div>
  );
}

interface TileProps {
  entry: MediaEntry;
  index: number;
  picture: string;
  suppliesSwatch: boolean;
  state: string[];
  onDragStart: () => void;
  onDragOver: () => void;
  onDrop: () => void;
  onDragEnd: () => void;
  onOpen: () => void;
  onFocus: () => void;
  onRemove: () => void;
}

/** One tile. Its own component so a video's clip has somewhere to keep the
 * element its hover plays. */
function ReelTile({
  entry,
  index,
  picture,
  suppliesSwatch,
  state,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onOpen,
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
      onDragStart={onDragStart}
      onDragOver={(event) => {
        event.preventDefault();
        onDragOver();
      }}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
    >
      <div
        className="rtile__face"
        onClick={onOpen}
        onMouseEnter={() => {
          onFocus();
          if (isVideo) play();
        }}
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
          <img src={picture} alt={label} loading="lazy" />
        )}
        <span className="rtile__pos">{index + 1}</span>
        {suppliesSwatch && (
          <span className="rtile__swatch" title="Supplies this colour's Etsy swatch">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2l10 10-10 10L2 12z" />
            </svg>
          </span>
        )}
        <span
          className="rtile__x"
          role="button"
          aria-label={`Remove ${label}`}
          // The × sits inside the face, which opens the carousel -- so
          // removing a tile must not also open the one that slid into its
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
