import { useRef, type RefObject } from "react";

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
