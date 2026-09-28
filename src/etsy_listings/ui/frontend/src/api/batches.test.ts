import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BatchesApiError,
  cancelStaging,
  confirmStaging,
  getBatch,
  getStaging,
  patchStaging,
  retryBatchRow,
  stageDesigns,
  StagingRefused,
  stagingThumbnailUrl,
} from "./batches";
import { api } from "./client";

function answer(status: number, data?: unknown, error?: unknown) {
  return { data, error, response: new Response(null, { status }) } as never;
}

function reply(status: number, body: unknown) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

afterEach(() => vi.restoreAllMocks());

describe("batches api", () => {
  it("stages files as multipart with the listing template", async () => {
    const fetch = reply(200, { id: "s1" });
    const file = new File(["x"], "a.png", { type: "image/png" });

    await expect(stageDesigns("heavyweight-tee", [file])).resolves.toEqual({ id: "s1" });

    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/staging");
    const form = init.body as FormData;
    expect(form.get("listing_template")).toBe("heavyweight-tee");
    expect((form.getAll("files")[0] as File).name).toBe("a.png");
  });

  it("turns a 422 refusal into StagingRefused, and anything else into its sentence", async () => {
    const refusal = { message: "a.zip is a ZIP", remedy: "Nothing was uploaded or changed." };
    reply(422, { detail: refusal });
    await expect(stageDesigns("t", [])).rejects.toEqual(new StagingRefused(refusal));

    reply(404, { detail: "no listing template 't'" });
    await expect(stageDesigns("t", [])).rejects.toThrow("no listing template 't'");
  });

  it("fills a partial edit out to the whole patch", async () => {
    const patch = vi.spyOn(api, "PATCH").mockResolvedValue(answer(200, { id: "s1" }));

    await patchStaging("s1", { remove: ["r1"] });

    expect((patch.mock.calls[0]?.[1] as unknown as { body: unknown }).body).toEqual({
      names: {},
      remove: ["r1"],
      label: null,
    });
  });

  it("passes on the server's sentence, or its own, when a call fails", async () => {
    vi.spyOn(api, "GET").mockResolvedValue(answer(404, undefined, { detail: "no batch 'b'" }));
    await expect(getBatch("b")).rejects.toThrow("no batch 'b'");
    await expect(getStaging("s")).rejects.toBeInstanceOf(BatchesApiError);

    vi.spyOn(api, "POST").mockResolvedValue(answer(409, undefined, { detail: "Fix 1 names" }));
    await expect(confirmStaging("s")).rejects.toThrow("Fix 1 names");
    await expect(retryBatchRow("b", "r")).rejects.toThrow("Fix 1 names");

    vi.spyOn(api, "PATCH").mockResolvedValue(answer(404, undefined, {}));
    await expect(patchStaging("s", {})).rejects.toThrow("The change was not saved.");

    vi.spyOn(api, "DELETE").mockResolvedValue(answer(404));
    await expect(cancelStaging("s")).rejects.toBeInstanceOf(BatchesApiError);
  });

  it("escapes a row's thumbnail url", () => {
    expect(stagingThumbnailUrl("s 1", "r/2")).toBe("/api/staging/s%201/rows/r%2F2/thumbnail");
  });
});
