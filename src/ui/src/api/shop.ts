import { api } from "./client";
import type { components } from "./schema";

/**
 * The Admin page's Shop tab over HTTP (`server/api/shop.py`). A save is
 * revision-checked: it names the revision it was made against and answers
 * with the next one, a conflict, or field errors keyed by change name.
 */

export type ShopSettings = components["schemas"]["ShopSettingsResponse"];
export type ShopChanges = components["schemas"]["ShopChanges"];
export type ShopConnections = components["schemas"]["ShopConnectionsResponse"];
export type ConnectionRow = components["schemas"]["ConnectionRowBody"];
export type ShopLookups = components["schemas"]["ShopLookupsResponse"];
export type ReturnPolicyTerms = components["schemas"]["ReturnPolicyTermsBody"];
type Refusal = components["schemas"]["ShopSaveRefusal"];

export type ShopField = keyof ShopChanges;

export type SaveOutcome =
  | { kind: "saved"; shop: ShopSettings }
  | { kind: "conflict"; message: string }
  | { kind: "invalid"; message: string; fieldErrors: Partial<Record<ShopField, string>> };

export class ShopApiError extends Error {}

/** shop.yaml's dotted keys back to the change names the page edits. */
function fieldOf(key: string): string {
  return key.replace(/^etsy\.listing_defaults\./, "").replace(/^(etsy|printify)\./, "");
}

function detailOf(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : fallback;
}

export async function getShop(): Promise<ShopSettings> {
  const { data, error } = await api.GET("/api/admin/shop");
  if (error || !data) throw new ShopApiError(detailOf(error, "could not read shop.yaml"));
  return data;
}

export async function saveShop(revision: string, changes: ShopChanges): Promise<SaveOutcome> {
  const { data, error, response } = await api.PATCH("/api/admin/shop", {
    body: { revision, changes },
  });
  if (data) return { kind: "saved", shop: data };
  const refusal = error as Refusal | undefined;
  if (response.status === 409 && refusal?.kind === "conflict")
    return { kind: "conflict", message: refusal.message };
  if (response.status === 422 && refusal?.kind === "invalid") {
    const fieldErrors = Object.fromEntries(
      Object.entries(refusal.field_errors ?? {}).map(([key, message]) => [fieldOf(key), message]),
    );
    return { kind: "invalid", message: refusal.message, fieldErrors };
  }
  throw new ShopApiError("could not save shop.yaml");
}

export async function getShopConnections(): Promise<ShopConnections> {
  const { data, error } = await api.GET("/api/admin/shop/connections");
  if (error || !data) throw new ShopApiError("could not read the connected shops");
  return data;
}

export async function getShopLookups(): Promise<ShopLookups> {
  const { data, error } = await api.GET("/api/admin/shop/lookups");
  if (error || !data) throw new ShopApiError("could not look up the shop's lists");
  return data;
}
