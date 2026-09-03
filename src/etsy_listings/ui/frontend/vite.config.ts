import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxies /api to uvicorn (etsy-listings ui, default port 8000); the
// production build's dist/ is served by that same FastAPI app with an SPA
// fallback, so no proxy is needed there.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
