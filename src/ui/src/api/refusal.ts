import type { components } from "./schema";

/**
 * How a revision-checked write refuses: settings.yaml and shop.yaml saves,
 * backup set-up, Create a new repository, Connect and restore. Every adapter
 * answers its success or one of these, so a page words a refusal one way.
 *
 * - `stale`: the file changed since the page read it. Nothing was written;
 *   reload, then try again.
 * - `refused`: the server says what is wrong, in `message` and the fields it
 *   names. `connectFrom` is a destination holding a repository's copy, which
 *   Create refused: connect it instead.
 */
export type Refusal =
  | { kind: "stale"; message: string }
  | {
      kind: "refused";
      message: string;
      fieldErrors: Record<string, string>;
      connectFrom?: string;
    };

type Body = Partial<components["schemas"]["BackupRefusal"]>;

/** `stale` (412) means reload; these say what is wrong. */
const REFUSED = new Set<Body["kind"]>(["conflict", "invalid"]);

/**
 * The refusal an error body carries, or null when it carries none (a server
 * error, or no answer). The body's `kind` decides, never the HTTP status.
 */
export function refusalOf(error: unknown): Refusal | null {
  const body = error as Body | undefined;
  const message = body?.message;
  if (typeof message !== "string") return null;
  if (body?.kind === "stale") return { kind: "stale", message };
  if (!REFUSED.has(body?.kind)) return null;
  return {
    kind: "refused",
    message,
    fieldErrors: body?.field_errors ?? {},
    ...(body?.connect_from && { connectFrom: body.connect_from }),
  };
}
