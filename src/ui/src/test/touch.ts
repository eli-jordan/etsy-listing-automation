import { vi } from "vitest";
import { PHONE_QUERY } from "../phone/usePhone";

/**
 * A finger on one element, for the phone gesture tests: jsdom has no touch,
 * so these dispatch the pointer events `useSwipe` reads.
 */

let pointer = 0;

function send(element: Element, type: string, x: number, y: number, id: number) {
  const event = new PointerEvent(type, {
    bubbles: true,
    clientX: x,
    clientY: y,
    pointerId: id,
    pointerType: "touch",
    isPrimary: true,
  });
  // The setup file's stand-in PointerEvent drops `isPrimary`.
  if (!event.isPrimary) Object.defineProperty(event, "isPrimary", { value: true });
  element.dispatchEvent(event);
}

/** A finger down at `from`, through `steps` moves to `to`, then up unless
 * `lift` is false (the finger still down, to look at the drag). */
export function drag(
  element: Element,
  from: [number, number],
  to: [number, number],
  { lift = true, steps = 4 } = {},
) {
  pointer += 1;
  const id = pointer;
  send(element, "pointerdown", from[0], from[1], id);
  for (let step = 1; step <= steps; step += 1) {
    const t = step / steps;
    send(
      element,
      "pointermove",
      from[0] + (to[0] - from[0]) * t,
      from[1] + (to[1] - from[1]) * t,
      id,
    );
  }
  if (lift) send(element, "pointerup", to[0], to[1], id);
}

/** The page pinch-zoomed to `scale` (1 is not zoomed). */
export function zoomedTo(scale: number) {
  vi.stubGlobal("visualViewport", {
    scale,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  });
}

/** The phone layout showing, and the seller's motion preference. */
export function onPhone({ reducedMotion = false, phone = true } = {}) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches:
      (phone && query === PHONE_QUERY) || (reducedMotion && query.includes("reduced-motion")),
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}
