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
 * The listing's gallery in the order Etsy will show it, reorderable by drag.
 * Position 2 is where Etsy pins the featured video. A drop `mediaEdits` refuses
 * changes nothing, and the tile snaps back.
 */

interface Props {
  media: readonly MediaEntry[];
  scene: Artwork | null;
  swatchTemplate: string | null;
  selectedIndex: number | null;
  listing: MediaOwner | string | null;
  files: readonly MediaFileSummary[];
  onRemove: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onFocus: (focus: Focus) => void;
  positioned?: ReadonlySet<string>;
  onAdd?: () => void;
  onView?: (index: number) => void;
  onDeselect?: () => void;
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

/** Phone browsers carry a dragged tile only sometimes, after a long press, so a
 * selected tile gets a bar that moves it under the same rules a drop obeys. */
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
        // Firefox starts no drag without a payload. A synthetic drag has no `dataTransfer`.
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
        // Left to the browser, a drop opens the dropped picture as the page.
        event.preventDefault();
        onDrop();
      }}
      onDragEnd={onDragEnd}
    >
      <div
        className="rtile__face"
        // A click, not a hover: the pointer crosses the reel on its way below,
        // and each tile it passed would start another full render.
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
