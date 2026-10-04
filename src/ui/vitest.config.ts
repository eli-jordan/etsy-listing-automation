import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separate from vite.config.ts so dev/build stay untouched by test-only
// config. Coverage enforcement mirrors the Python side (pyproject.toml):
// branch coverage, 85% floor -- and lives only in `test:coverage`, not the
// plain `test` script, so running one component's tests locally doesn't fail
// a whole-suite gate it was never going to meet (same reasoning as Python's
// coverage being deliberately absent from pytest's default addopts).
//
// Three projects, one per execution environment a test actually needs:
//
//   node   -- pure subjects: reducers, geometry, formatting, media/plan
//             arithmetic. No DOM, no setup file. A module only belongs here
//             if neither it nor its test touches window/document/storage/
//             fetch/EventSource; adding a DOM dependency to one fails its
//             tests here instead of passing by accident under jsdom.
//   dom    -- everything else under src/: components, hooks, storage and the
//             transport modules (fetch/Blob/EventSource are browser APIs the
//             app runs against), with jsdom and setup.ts.
//   design -- the marver prototype frames' own tests. Required (check.sh and
//             CI run `test:design`), but kept out of `test:coverage`: the
//             frames import production components, and exercising those from
//             a prototype is not production coverage.
const NODE_TESTS = [
  "src/dates.test.ts",
  "src/media.test.ts",
  "src/components/quadGeometry.test.ts",
  "src/pages/batchDeploy/batchDeployPresentation.test.ts",
  "src/pages/batchDeploy/batchDeployState.test.ts",
  "src/pages/deploy/comparison.test.ts",
  "src/pages/deploy/deployState.test.ts",
  "src/pages/deploy/listingRunState.test.ts",
  "src/pages/deploy/wordDiff.test.ts",
  "src/pages/editor/colourSelection.test.ts",
  "src/pages/editor/focus.test.ts",
  "src/pages/editor/mediaEdits.test.ts",
];

const jsdom = {
  environment: "jsdom",
  setupFiles: ["./src/test/setup.ts"],
  // `list`, not the default `stack`: setup.ts's `cleanup()` must unmount
  // before a test file's own `afterEach(() => vi.restoreAllMocks())`.
  // Unmounting flushes pending effects, and under `stack` those ran against
  // real, just-restored API functions -- a stray `fetch` of a relative URL
  // that failed CI as an unhandled error (BatchDeployPage's mark-seen).
  sequence: { hooks: "list" },
} as const;

export default defineConfig({
  plugins: [react()],
  test: {
    projects: [
      {
        extends: true,
        test: { name: "node", environment: "node", include: NODE_TESTS },
      },
      {
        extends: true,
        test: {
          name: "dom",
          ...jsdom,
          include: ["src/**/*.test.{ts,tsx}"],
          exclude: [...configDefaults.exclude, ...NODE_TESTS],
        },
      },
      {
        extends: true,
        test: { name: "design", ...jsdom, include: ["design/**/*.test.{ts,tsx}"] },
      },
    ],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      thresholds: {
        branches: 85,
      },
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/api/schema.ts", "src/main.tsx", "src/test/**", "**/*.d.ts", "**/*.test.*"],
    },
  },
});
