import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { usePager } from "../phone/usePager";
import { useIsPhone } from "../phone/usePhone";
import { useSheetDrag } from "../phone/useSheetDrag";

/**
 * One preview, as large as the screen allows, over everything else.
 *
 * The Preview tab exists to be *judged* from, and a 140px tile cannot answer
 * the questions calibration is actually about -- whether the print's edge is
 * following a fold, whether the shading has gone muddy, whether the artwork
 * sits a few millimetres high. So a tile opens here, and here has a 1:1 view:
 * at fit-to-screen a 4000px render is being downsampled by the browser, which
 * is the one thing guaranteed to hide a resampling artefact.
 *
 * Arrow keys walk the set. That is the whole point for a colour matrix -- the
 * fault you are looking for is usually "this one colour is wrong", and finding
 * it means comparing neighbours, not opening and closing twelve times.
 */

export interface LightboxItem {
  id: string;
  label: string;
  url: string;
  /** A video plays with the browser's own controls instead. */
  kind?: "image" | "video";
}

interface Props {
  items: LightboxItem[];
  index: number;
  /** True pixels rather than fit-to-screen. Owned by the parent so it
   * survives stepping between images -- having to re-press it on every
   * neighbour would defeat comparing them. */
  actualSize: boolean;
  onActualSizeChange: (actual: boolean) => void;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}

export function Lightbox({
  items,
  index,
  actualSize,
  onActualSizeChange,
  onIndexChange,
  onClose,
}: Props) {
  const item = items[index];
  const closeRef = useRef<HTMLButtonElement>(null);

  const step = useCallback(
    (delta: number) => {
      if (items.length < 2) return;
      onIndexChange((index + delta + items.length) % items.length);
    },
    [index, items.length, onIndexChange],
  );

  // On the window, not on the dialog: the dialog is what has focus when it
  // opens, but a click on the image or a scroll of the 1:1 view moves it, and
  // Escape has to keep working afterwards.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      else if (event.key === "ArrowRight") step(1);
      else if (event.key === "ArrowLeft") step(-1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, step]);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  const isPhone = useIsPhone();
  const root = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  // On a phone a sideways swipe on the picture pages through the set, and a
  // swipe down closes. At 1:1 a finger pans the picture, so neither is armed
  // then.
  usePager(stage, {
    items: items.map((_, position) => position),
    current: index,
    enabled: !actualSize,
    onPick: onIndexChange,
  });
  useSheetDrag(root, { moves: stage, fade: true, enabled: !actualSize, onDismiss: onClose });

  if (!item) return null;

  const box = (
    <div
      ref={root}
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`${item.label}, preview ${index + 1} of ${items.length}`}
      // Only a press that both starts and ends on the backdrop closes it:
      // releasing a drag from inside the image happens to land on the backdrop
      // and would otherwise shut the thing you are studying.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="lightbox__bar">
        <span className="lightbox__label">{item.label}</span>
        {items.length > 1 && (
          <span className="lightbox__count">{`${index + 1} / ${items.length}`}</span>
        )}
        <div className="lightbox__actions">
          {items.length > 1 && (
            <>
              <button type="button" onClick={() => step(-1)} aria-label="Previous preview">
                ←
              </button>
              <button type="button" onClick={() => step(1)} aria-label="Next preview">
                →
              </button>
            </>
          )}
          <button
            type="button"
            className={actualSize ? "seg-opt seg-opt--on" : "seg-opt"}
            aria-pressed={actualSize}
            onClick={() => onActualSizeChange(!actualSize)}
          >
            1:1
          </button>
          <button type="button" ref={closeRef} onClick={onClose}>
            Close ✕
          </button>
        </div>
      </div>

      <div
        ref={stage}
        className={actualSize ? "lightbox__stage lightbox__stage--actual" : "lightbox__stage"}
      >
        {item.kind === "video" ? (
          <video
            key={item.id}
            src={item.url}
            aria-label={item.label}
            className="lightbox__image"
            controls
            playsInline
            preload="metadata"
          />
        ) : (
          <img src={item.url} alt={item.label} className="lightbox__image" />
        )}
      </div>
    </div>
  );
  // On the body on a phone, out of the editor's swiping tab content.
  return isPhone ? createPortal(box, document.body) : box;
}
