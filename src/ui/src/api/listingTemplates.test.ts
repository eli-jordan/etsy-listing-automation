import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import {
  createListingTemplate,
  deleteListingTemplate,
  getListingTemplateDraft,
  ListingTemplateNameRefused,
  ListingTemplatesApiError,
  listingTemplateMediaThumbnailUrl,
  listListingTemplates,
} from "./listingTemplates";

function answer(status: number, data?: unknown, error?: unknown) {
  return { data, error, response: new Response(null, { status }) } as never;
}

afterEach(() => vi.restoreAllMocks());

describe("listing templates api", () => {
  it("lists the cards, and fails loudly", async () => {
    vi.spyOn(api, "GET").mockResolvedValueOnce(answer(200, []));
    await expect(listListingTemplates()).resolves.toEqual([]);

    vi.spyOn(api, "GET").mockResolvedValueOnce(answer(500, undefined, {}));
    await expect(listListingTemplates()).rejects.toBeInstanceOf(ListingTemplatesApiError);
  });

  it("asks for a draft by its one source", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue(answer(200, { media: [] }));

    await getListingTemplateDraft({ kind: "listing", name: "take-a-hike" });
    await getListingTemplateDraft({ kind: "listing-template", name: "tee" });

    expect(get.mock.calls.map((call) => (call[1] as { params: unknown }).params)).toEqual([
      { query: { from_listing: "take-a-hike" } },
      { query: { from_template: "tee" } },
    ]);
  });

  it("passes on the server's sentence when a draft cannot be made", async () => {
    vi.spyOn(api, "GET").mockResolvedValueOnce(
      answer(422, undefined, { detail: "./shots/gone.png cannot be copied" }),
    );
    await expect(getListingTemplateDraft({ kind: "listing", name: "x" })).rejects.toThrow(
      "./shots/gone.png cannot be copied",
    );

    vi.spyOn(api, "GET").mockResolvedValueOnce(answer(500, undefined, {}));
    await expect(getListingTemplateDraft({ kind: "listing", name: "x" })).rejects.toThrow(
      "could not read x",
    );
  });

  it("tells a refused name apart from any other failure", async () => {
    vi.spyOn(api, "POST").mockResolvedValueOnce(answer(409, undefined, {}));
    const taken = createListingTemplate("tee", { kind: "listing", name: "x" });
    await expect(taken).rejects.toBeInstanceOf(ListingTemplateNameRefused);
    await expect(taken).rejects.toThrow("that name is already taken");

    vi.spyOn(api, "POST").mockResolvedValueOnce(answer(400, undefined, {}));
    await expect(createListingTemplate("../x", { kind: "listing", name: "x" })).rejects.toThrow(
      "that is not a usable name",
    );

    vi.spyOn(api, "POST").mockResolvedValueOnce(answer(500, undefined, {}));
    await expect(createListingTemplate("tee", { kind: "listing", name: "x" })).rejects.toThrow(
      "could not save tee",
    );
  });

  it("resolves a create the server declined to write, with its issues", async () => {
    const result = { saved: false, issues: [], field_errors: {}, template: null };
    const post = vi.spyOn(api, "POST").mockResolvedValue(answer(200, result));

    await expect(
      createListingTemplate("tee", { kind: "listing-template", name: "hike" }),
    ).resolves.toEqual(result);
    expect(post.mock.calls[0]?.[1]).toEqual({ body: { name: "tee", from_template: "hike" } });
  });

  it("deletes, and says when it could not", async () => {
    vi.spyOn(api, "DELETE").mockResolvedValueOnce(answer(204));
    await expect(deleteListingTemplate("tee")).resolves.toBeUndefined();

    vi.spyOn(api, "DELETE").mockResolvedValueOnce(answer(404, undefined, {}));
    await expect(deleteListingTemplate("tee")).rejects.toBeInstanceOf(ListingTemplatesApiError);
  });

  it("escapes a file path a segment at a time", () => {
    expect(listingTemplateMediaThumbnailUrl("my tee", "assets/a b.png")).toBe(
      "/api/listing-templates/my%20tee/media-files/assets/a%20b.png/thumbnail",
    );
  });
});
