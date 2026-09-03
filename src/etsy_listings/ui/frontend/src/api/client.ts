import createClient from "openapi-fetch";
import type { paths } from "./schema";

// The base path is empty: Vite's dev proxy forwards /api to uvicorn, and the
// production build is served *by* the same FastAPI app, so both cases resolve
// relative to the page's own origin.
export const api = createClient<paths>({ baseUrl: "" });
