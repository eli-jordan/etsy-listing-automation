import createClient from "openapi-fetch";
import type { paths } from "./schema";

// The base path is empty: Vite's dev proxy forwards /api to uvicorn, and the
// production build is served *by* the same FastAPI app, so both cases resolve
// relative to the page's own origin.
export const api = createClient<paths>({ baseUrl: "" });

type Widened<T> = T extends readonly (infer Item)[]
  ? Widened<Item>[]
  : T extends object
    ? { [K in keyof T]: Widened<T[K]> }
    : T;

/** The generated type of a response whose fixed-length tuples (a
 * `BoundingBox`'s four corners, a swatch's RGB triple) openapi-fetch's
 * inference widened to plain arrays. The server's response model validates
 * the exact lengths. */
export function withTuples<T>(data: Widened<T>): T {
  return data as T;
}

/** A multipart body. openapi-fetch sends a `FormData` as it is and lets the
 * browser set the boundary, but the generated request type spells each file
 * field as `string`. */
export function formBody<Body>(form: FormData): Body {
  return form as unknown as Body;
}

/** The server's own sentence for a refusal: `detail` when it is a string. A
 * validation error's `detail` is a list, and is not for the seller. */
export function detailMessage(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : fallback;
}
