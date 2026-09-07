import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Unmounts every rendered tree after each test -- without this, a component
// left mounted from a previous test keeps its debounced effects (preview
// fetches) alive, and they can fire later against mocks a subsequent test
// has already restored.
afterEach(() => {
  cleanup();
});

// jsdom doesn't implement object URLs; the calibrator creates one per
// preview PNG and revokes the previous one on every render.
globalThis.URL.createObjectURL = vi.fn(() => "blob:mock-url");
globalThis.URL.revokeObjectURL = vi.fn();

// jsdom implements neither `PointerEvent` nor pointer capture, and without
// them a synthetic pointerdown arrives with no `button` at all -- so a handler
// that (correctly) ignores anything but the primary button ignores everything,
// and the whole canvas looks inert to a test. MouseEvent already carries
// `button` and the client coordinates; the pointer identity is the only thing
// added. Capture is a no-op: there is no second target for events to be
// retargeted away from.
if (!("PointerEvent" in globalThis)) {
  class TestPointerEvent extends MouseEvent {
    readonly pointerId: number;
    readonly pointerType: string;

    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
      this.pointerType = init.pointerType ?? "mouse";
    }
  }
  globalThis.PointerEvent = TestPointerEvent as unknown as typeof PointerEvent;
}

const capture = Element.prototype as unknown as Record<string, unknown>;
capture.setPointerCapture ??= () => {};
capture.releasePointerCapture ??= () => {};
capture.hasPointerCapture ??= () => false;
