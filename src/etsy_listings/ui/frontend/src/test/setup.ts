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
