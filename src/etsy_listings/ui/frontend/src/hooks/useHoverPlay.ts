import { useRef, type RefObject } from "react";

/**
 * Play a muted clip while the pointer is over whatever holds it, and put it
 * back on its poster frame after (PRD 71). The holder -- a locator row, a
 * reel tile's face -- owns the hover, so the actions come out here and the
 * element goes to `MutedClip` through `ref`.
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
