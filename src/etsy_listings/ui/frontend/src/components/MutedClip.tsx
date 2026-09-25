import { useRef, type RefObject } from "react";

/**
 * A video drawn as a tile: muted, reading only its metadata, resting on a
 * frame half a second in, and playing while the pointer is over whatever
 * holds it (PRD 71).
 *
 * The locator's file list and the reel both draw clips this way, and the
 * hover belongs to the *holder* -- a locator row, a reel tile's face -- not to
 * the `<video>`, which is why the play and rest actions come out of a hook
 * rather than living inside the element. No poster image is fetched: the
 * `#t=` media fragment makes the browser draw that frame itself, and the
 * thumbnail endpoint refuses a video for exactly that reason.
 */

/** Where a muted clip rests: half a second in, since a first frame is often
 * black. */
export const POSTER_TIME = 0.5;

export interface HoverPlay {
  ref: RefObject<HTMLVideoElement | null>;
  play: () => void;
  rest: () => void;
}

export function useHoverPlay(): HoverPlay {
  const ref = useRef<HTMLVideoElement>(null);
  return {
    ref,
    play() {
      const clip = ref.current;
      if (clip === null) return;
      clip.currentTime = 0;
      // A browser may refuse autoplay; the poster frame stays, which is fine.
      void clip.play()?.catch(() => {});
    },
    rest() {
      const clip = ref.current;
      if (clip === null) return;
      clip.pause();
      clip.currentTime = POSTER_TIME;
    },
  };
}

interface Props {
  src: string;
  clip: HoverPlay;
  label?: string;
  onDuration?: (seconds: number) => void;
}

export function MutedClip({ src, clip, label, onDuration }: Props) {
  return (
    <video
      ref={clip.ref}
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
