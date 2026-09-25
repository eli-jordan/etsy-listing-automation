import type { RefObject } from "react";
import { POSTER_TIME } from "../hooks/useHoverPlay";

/**
 * A video drawn as a tile: muted, reading only its metadata, resting on a
 * frame half a second in, and playing while the pointer is over whatever
 * holds it (PRD 71).
 *
 * The locator's file list and the reel both draw clips this way, and the
 * hover belongs to the *holder* -- a locator row, a reel tile's face -- not to
 * the `<video>`, which is why the play and rest actions come out of
 * `useHoverPlay` and the element goes back to it through `clipRef`. No poster
 * image is fetched: the `#t=` media fragment makes the browser draw that
 * frame itself, and the thumbnail endpoint refuses a video for exactly that
 * reason.
 */

interface Props {
  src: string;
  clipRef: RefObject<HTMLVideoElement | null>;
  label?: string;
  onDuration?: (seconds: number) => void;
}

export function MutedClip({ src, clipRef, label, onDuration }: Props) {
  return (
    <video
      ref={clipRef}
      src={`${src}#t=${POSTER_TIME}`}
      aria-label={label}
      preload="metadata"
      muted
      loop
      playsInline
      onLoadedMetadata={
        onDuration === undefined ? undefined : (event) => onDuration(event.currentTarget.duration)
      }
    />
  );
}
