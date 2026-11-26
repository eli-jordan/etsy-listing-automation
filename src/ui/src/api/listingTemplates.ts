import { api } from "./client";
import { escapedEachSegment } from "./listings";
import type {
  MediaFileSummary,
  ListingTemplateDetail,
  ListingTemplateSaveResult,
  ListingTemplateSource,
  ListingTemplateSummary,
} from "../types";

export class ListingTemplatesApiError extends Error {}

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

export async function getListingTemplateDraft(
  source: ListingTemplateSource,
): Promise<ListingTemplateDetail> {
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

/** `document`: the seller's edits made before naming it. */
export async function createListingTemplate(
  name: string,
  source: ListingTemplateSource,
  document?: Record<string, unknown>,
): Promise<ListingTemplateSaveResult> {
  const { data, error, response } = await api.POST("/api/listing-templates", {
    body: { name, ...sourceQuery(source), ...(document === undefined ? {} : { document }) },
  });
  if (response.status === 409 || response.status === 400) {
    throw new ListingTemplateNameRefused(name, response.status === 409);
  }
  if (error || !data) throw new ListingTemplatesApiError(`could not save ${name}`);
  return data;
}

export async function getListingTemplate(name: string): Promise<ListingTemplateDetail> {
  const { data, error } = await api.GET("/api/listing-templates/{name}", {
    params: { path: { name } },
  });
  if (error || !data) throw new ListingTemplatesApiError(`failed to load listing template ${name}`);
  return data;
}

export async function putListingTemplate(
  name: string,
  document: Record<string, unknown>,
): Promise<ListingTemplateSaveResult> {
  const { data, error } = await api.PUT("/api/listing-templates/{name}", {
    params: { path: { name } },
    body: document,
  });
  if (error || !data) throw new ListingTemplatesApiError(`could not save ${name}`);
  return data;
}

export async function renameListingTemplate(
  name: string,
  newName: string,
): Promise<ListingTemplateDetail> {
  const { data, error, response } = await api.POST("/api/listing-templates/{name}/rename", {
    params: { path: { name } },
    body: { new_name: newName },
  });
  if (response.status === 409 || response.status === 400) {
    throw new ListingTemplateNameRefused(newName, response.status === 409);
  }
  if (error || !data) throw new ListingTemplatesApiError(`could not rename ${name}`);
  return data;
}

export async function deleteListingTemplate(name: string): Promise<void> {
  const { response } = await api.DELETE("/api/listing-templates/{name}", {
    params: { path: { name } },
  });
  if (response.status !== 204) throw new ListingTemplatesApiError(`could not delete ${name}`);
}

export async function listListingTemplateMediaFiles(name: string): Promise<MediaFileSummary[]> {
  const { data, error } = await api.GET("/api/listing-templates/{template}/media-files", {
    params: { path: { template: name } },
  });
  if (error || !data) throw new ListingTemplatesApiError(`could not load ${name}'s files`);
  return data;
}

export function listingTemplateMediaThumbnailUrl(template: string, path: string): string {
  return `/api/listing-templates/${encodeURIComponent(template)}/media-files/${escapedEachSegment(path)}/thumbnail`;
}

export function listingTemplateMediaFileUrl(template: string, path: string): string {
  return `/api/listing-templates/${encodeURIComponent(template)}/media-files/${escapedEachSegment(path)}/file`;
}
