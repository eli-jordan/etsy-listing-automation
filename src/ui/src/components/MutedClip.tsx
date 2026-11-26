import type { RefObject } from "react";
import { POSTER_TIME } from "../hooks/useHoverPlay";

/**
 * A muted clip resting half a second in, played by whatever holds it
 * (`useHoverPlay`). The `#t=` media fragment draws the rest frame, so no poster
 * is fetched.
 */

interface Props {
  src: string;
  clipRef?: RefObject<HTMLVideoElement | null>;
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
