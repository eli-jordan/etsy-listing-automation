/**
 * The one feel every phone swipe shares, for `usePager` and `useSheetDrag`:
 * how an element follows a finger, springs back, and leaves.
 */

const SPRING_MS = 180;
const SPRING = `transform ${SPRING_MS}ms ease-out, opacity ${SPRING_MS}ms ease-out`;

/** Whether the seller asked for less motion: then a swipe acts at once. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Puts `element` at `transform` (empty for its resting place) over
 * `transition`, at `opacity` (empty for the stylesheet's). */
export function pose(element: HTMLElement, transform: string, transition: string, opacity = "") {
  element.style.transition = transition;
  element.style.transform = transform;
  element.style.opacity = opacity;
}

/** A release short of a swipe: the element springs back to its resting
 * place, then hands its transitions back to the stylesheet (a drawer's own
 * height transition, say). */
export function springBack(element: HTMLElement) {
  if (element.style.transform === "") {
    pose(element, "", "");
    return;
  }
  pose(element, "", SPRING);
  window.setTimeout(() => {
    if (element.style.transition === SPRING) element.style.transition = "";
  }, SPRING_MS);
}
