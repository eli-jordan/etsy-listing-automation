const SPRING_MS = 180;
const SPRING = `transform ${SPRING_MS}ms ease-out, opacity ${SPRING_MS}ms ease-out`;

export function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** An empty `transform` is the resting place, an empty `opacity` the stylesheet's. */
export function pose(element: HTMLElement, transform: string, transition: string, opacity = "") {
  element.style.transition = transition;
  element.style.transform = transform;
  element.style.opacity = opacity;
}

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
