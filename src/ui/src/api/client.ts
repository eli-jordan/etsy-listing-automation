import createClient from "openapi-fetch";
import type { paths } from "./schema";

// Same origin: Vite's dev proxy forwards /api, and production is served by the FastAPI app.
export const api = createClient<paths>({ baseUrl: "" });

type Widened<T> = T extends readonly (infer Item)[]
  ? Widened<Item>[]
  : T extends object
    ? { [K in keyof T]: Widened<T[K]> }
    : T;

/** openapi-fetch widens fixed-length tuples (a `BoundingBox`'s corners, an RGB
 * triple) to arrays; the server's response model checks the lengths. */
export function withTuples<T>(data: Widened<T>): T {
  return data as T;
}

/** The generated request type spells a file field `string`; openapi-fetch
 * sends a `FormData` as it is and the browser sets the boundary. */
export function formBody<Body>(form: FormData): Body {
  return form as unknown as Body;
}

export function detailMessage(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : fallback;
}
