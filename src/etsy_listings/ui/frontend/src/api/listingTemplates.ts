import { api } from "./client";
import type {
  ListingTemplateDraft,
  ListingTemplateSaveResult,
  ListingTemplateSource,
  ListingTemplateSummary,
} from "../types";

/**
 * The listing-templates resource (A35, A36): typed wrappers over
 * `/api/listing-templates`, in `api/listings.ts`'s shape.
 */

export class ListingTemplatesApiError extends Error {}

/** A name the server will not take: already a listing template's (409), or
 * not a usable directory name (400). Its own class because the *name it*
 * page shows it beside the name field rather than as a page error. */
export class ListingTemplateNameRefused extends ListingTemplatesApiError {
  constructor(
    readonly name: string,
    readonly taken: boolean,
  ) {
    super(taken ? "that name is already taken" : "that is not a usable name");
  }
}

export async function listListingTemplates(): Promise<ListingTemplateSummary[]> {
  const { data, error } = await api.GET("/api/listing-templates");
  if (error || !data) throw new ListingTemplatesApiError("could not load listing templates");
  return data;
}

function sourceQuery(source: ListingTemplateSource) {
  return source.kind === "listing" ? { from_listing: source.name } : { from_template: source.name };
}

/** The template Save as listing template (or Clone) would write, written
 * nowhere. Rejects with the server's sentence for a source that cannot
 * become one -- a `./` file that cannot be read names the file. */
export async function getListingTemplateDraft(
  source: ListingTemplateSource,
): Promise<ListingTemplateDraft> {
  const { data, error } = await api.GET("/api/listing-templates/draft", {
    params: { query: sourceQuery(source) },
  });
  if (error || !data) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    throw new ListingTemplatesApiError(
      typeof detail === "string" ? detail : `could not read ${source.name}`,
    );
  }
  return data;
}

/** Naming the draft is what writes it. Resolves for a template the server
 * would not write -- `saved: false` with its issues, nothing on disk -- and
 * rejects with {@link ListingTemplateNameRefused} for a name it will not
 * take, which is never suffixed. */
export async function createListingTemplate(
  name: string,
  source: ListingTemplateSource,
): Promise<ListingTemplateSaveResult> {
  const { data, error, response } = await api.POST("/api/listing-templates", {
    body: { name, ...sourceQuery(source) },
  });
  if (response.status === 409 || response.status === 400) {
    throw new ListingTemplateNameRefused(name, response.status === 409);
  }
  if (error || !data) throw new ListingTemplatesApiError(`could not save ${name}`);
  return data;
}

export async function deleteListingTemplate(name: string): Promise<void> {
  const { response } = await api.DELETE("/api/listing-templates/{name}", {
    params: { path: { name } },
  });
  if (response.status !== 204) throw new ListingTemplatesApiError(`could not delete ${name}`);
}

/** One of a listing template's own files (a `./` ref without the `./`),
 * downscaled for a card. Escaped a segment at a time, as the listing's own
 * file URLs are. */
export function listingTemplateMediaThumbnailUrl(template: string, path: string): string {
  const escaped = path.split("/").map(encodeURIComponent).join("/");
  return `/api/listing-templates/${encodeURIComponent(template)}/media-files/${escaped}/thumbnail`;
}
