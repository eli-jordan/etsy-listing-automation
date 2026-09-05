import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separate from vite.config.ts so dev/build stay untouched by test-only
// config. Coverage enforcement mirrors the Python side (pyproject.toml):
// branch coverage, 85% floor -- and lives only in `test:coverage`, not the
// plain `test` script, so running one component's tests locally doesn't fail
// a whole-suite gate it was never going to meet (same reasoning as Python's
// coverage being deliberately absent from pytest's default addopts).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
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
