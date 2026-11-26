import type { components } from "./schema";

/**
 * How a revision-checked write refuses. `stale`: nothing was written; reload,
 * then try again. `connectFrom`: a destination holding a copy of the
 * repository, which Create refused: connect it instead.
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

const REFUSED = new Set<Body["kind"]>(["conflict", "invalid"]);

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
