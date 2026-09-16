import { useState } from "react";
import { mediaLabel, pictureFor } from "../../media";
import type { CommonMediaSummary, MediaEntry } from "../../types";
import { MAX_MEDIA } from "./mediaEdits";
import type { Focus } from "./focus";

/**
 * The listing's images, in the order Etsy will show them, reorderable by drag.
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
  shared: readonly CommonMediaSummary[];
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
  shared,
  onOpen,
  onRemove,
  onReorder,
  onFocus,
}: Props) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  function focusFor(entry: MediaEntry) {
    if (typeof entry !== "string") {
      onFocus({ kind: "template", template: entry.template, colour: entry.colour ?? null });
      return;
    }
    // Only an asset still in common-media/ can be previewed; a ref whose file
    // has gone keeps its tile and its label, which is how the user finds out
    // it is missing.
    const asset = shared.find((a) => a.ref === entry);
    if (asset !== undefined) onFocus({ kind: "shared", asset });
  }

  return (
    <div className="reel">
      <div className="reel__head">
        <span className="reel__title">Listing images</span>
        <span className="reel__count">
          {media.length} of {MAX_MEDIA}
        </span>
        <span className="reel__hint">
          {media.length >= MAX_MEDIA
            ? `At Etsy's ${MAX_MEDIA}-image limit — remove one before adding another`
            : "Drag a tile to change the order Etsy shows them in"}
        </span>
      </div>
      <div className="reel__track">
        {media.map((entry, index) => {
          const isTemplate = typeof entry !== "string";
          const suppliesSwatch =
            isTemplate &&
            swatchTemplate !== null &&
            entry.template === swatchTemplate &&
            entry.colour !== null;
          const className = [
            "rtile",
            selectedIndex === index ? "rtile--selected" : "",
            dragIndex === index ? "rtile--dragging" : "",
            dragOverIndex === index && dragIndex !== index ? "rtile--over" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <div
              key={`${mediaLabel(entry)}-${index}`}
              className={className}
              draggable
              onDragStart={() => setDragIndex(index)}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverIndex(index);
              }}
              onDrop={() => {
                if (dragIndex !== null) onReorder(dragIndex, index);
                setDragIndex(null);
                setDragOverIndex(null);
              }}
              onDragEnd={() => {
                setDragIndex(null);
                setDragOverIndex(null);
              }}
            >
              <div
                className="rtile__face"
                onClick={() => onOpen(index)}
                onMouseEnter={() => focusFor(entry)}
              >
                <img
                  src={pictureFor(entry, design, "tile")}
                  alt={mediaLabel(entry)}
                  loading="lazy"
                />
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
                  aria-label={`Remove ${mediaLabel(entry)}`}
                  // The × sits inside the face, which now opens the carousel
                  // -- so removing an image must not also open the one that
                  // slid into its place.
                  onClick={(event) => {
                    event.stopPropagation();
                    onRemove(index);
                  }}
                >
                  ×
                </span>
                {index === 0 && <span className="rtile__first">Etsy thumbnail</span>}
              </div>
              <span className="rtile__label">{mediaLabel(entry)}</span>
            </div>
          );
        })}
        {media.length === 0 && (
          <p className="reel__empty">Nothing here yet — add a mockup template from the left.</p>
        )}
      </div>
    </div>
  );
}
