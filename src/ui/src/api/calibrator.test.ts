import type { PhotoWarpTemplate } from "../types";
import { afterEach, describe, expect, it, vi } from "vitest";
import { must } from "../test/helpers";
import type { ColourMatrixTemplate } from "../types";

/** The generated client's requests, answered with real `Response`s. `api`
 * captures `fetch` and `Request` when it is created, so each test stubs them
 * and then imports a fresh copy. The base URL is relative (the SPA is served
 * by the API's own origin); jsdom has no origin for undici's `Request`, so the
 * stub resolves it against one. */
const sent: Request[] = [];

type Answer = Response | Promise<Response>;

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** Answers each request in turn with `respond`, recording it in `sent`. */
function answeringWith(respond: (request: Request) => Answer) {
  sent.length = 0;
  vi.stubGlobal(
    "Request",
    class extends Request {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, "http://ui.test") : input, init);
      }
    },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      sent.push(request);
      return respond(request);
    }),
  );
  vi.resetModules();
  return import("./calibrator");
}

function answering(status: number, body: unknown, headers: Record<string, string> = {}) {
  return answeringWith(() => json(status, body, headers));
}

/** Method, path and If-Match of a recorded request, plus its JSON body. */
async function described(request: Request) {
  return {
    method: request.method,
    path: new URL(request.url).pathname,
    ifMatch: request.headers.get("If-Match"),
    body: request.method === "GET" ? undefined : await request.clone().json(),
  };
}

function onlyRequest(): Request {
  expect(sent).toHaveLength(1);
  return must(sent[0]);
}

const CONFIG: PhotoWarpTemplate<ColourMatrixTemplate> = {
  kind: "colour-matrix",
  bounding_box: [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
  ],
  renderer: {
    type: "photo-warp",
    config: {
      displace: { enabled: false, strength: 0 },
      shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
    },
  },
};

const SAVED_AT = "Wed, 17 Sep 2026 18:30:00 GMT";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("listTemplates", () => {
  it("GETs the template list and returns it", async () => {
    const { listTemplates } = await answering(200, [{ name: "a" }]);

    expect(await listTemplates()).toEqual([{ name: "a" }]);
    const request = onlyRequest();
    expect([request.method, new URL(request.url).pathname]).toEqual(["GET", "/api/templates"]);
  });

  it("throws CalibratorApiError on a 500", async () => {
    const { listTemplates, CalibratorApiError } = await answering(500, { detail: "boom" });

    await expect(listTemplates()).rejects.toBeInstanceOf(CalibratorApiError);
  });
});

describe("getTemplateConfig", () => {
  it("GETs the named template's config with its Last-Modified time", async () => {
    const { getTemplateConfig } = await answering(200, CONFIG, { "Last-Modified": SAVED_AT });

    expect(await getTemplateConfig("flat lay/01")).toEqual({
      config: CONFIG,
      modifiedAt: SAVED_AT,
    });
    const request = onlyRequest();
    expect(request.method).toBe("GET");
    expect(new URL(request.url).pathname).toBe("/api/templates/flat%20lay%2F01/config");
  });

  it("refuses a config the server sent without its modification time", async () => {
    const { getTemplateConfig, CalibratorApiError } = await answering(200, CONFIG);

    await expect(getTemplateConfig("flat-lay-01")).rejects.toBeInstanceOf(CalibratorApiError);
  });

  // Existing contract: every error answer reads as "no template.yaml yet",
  // not only the 404 the server sends for one -- a 500 is not told apart.
  it.each([404, 500])(
    "returns null for a %i, as for a template with no template.yaml",
    async (status) => {
      const { getTemplateConfig } = await answering(status, { detail: "no" });

      expect(await getTemplateConfig("brand-new")).toBeNull();
    },
  );
});

describe("saveTemplateConfig", () => {
  it("PUTs the config with the read revision and a request id, and returns the saved one", async () => {
    const saved = {
      ...CONFIG,
      renderer: {
        ...CONFIG.renderer,
        config: { ...CONFIG.renderer.config, displace: { enabled: true, strength: 4 } },
      },
    };
    const { getTemplateConfig, saveTemplateConfig } = await answeringWith((request) =>
      request.method === "GET"
        ? json(200, CONFIG, { ETag: '"sha256:read"', "Last-Modified": SAVED_AT })
        : json(200, saved, { ETag: '"sha256:saved"' }),
    );
    await getTemplateConfig("flat lay/01");

    expect(await saveTemplateConfig("flat lay/01", CONFIG)).toEqual(saved);
    expect(sent).toHaveLength(2);
    const request = must(sent[1]);
    expect(request.headers.get("Content-Type")).toBe("application/json");
    expect(await described(request)).toEqual({
      method: "PUT",
      path: "/api/templates/flat%20lay%2F01/config",
      ifMatch: '"sha256:read"',
      body: { request_id: expect.any(String), config: CONFIG, mask_edits: [] },
    });
  });

  it("sends a fresh request id with every save", async () => {
    const { saveTemplateConfig } = await answering(200, CONFIG, { ETag: '"sha256:saved"' });

    await saveTemplateConfig("flat-lay-01", CONFIG);
    await saveTemplateConfig("flat-lay-01", CONFIG);
    const [first, second] = await Promise.all(sent.map((r) => r.clone().json()));
    expect(first.request_id).toEqual(expect.any(String));
    expect(second.request_id).not.toBe(first.request_id);
  });

  it.each([404, 500])("throws CalibratorApiError on a %i", async (status) => {
    const { saveTemplateConfig, CalibratorApiError } = await answering(status, { detail: "bad" });

    await expect(saveTemplateConfig("flat-lay-01", CONFIG)).rejects.toBeInstanceOf(
      CalibratorApiError,
    );
  });

  it.each([409, 412])("tells the user to reload on a %i", async (status) => {
    const { saveTemplateConfig } = await answering(status, { detail: "stale" });

    await expect(saveTemplateConfig("flat-lay-01", CONFIG)).rejects.toThrow(
      "Template changed elsewhere. Reload before saving.",
    );
  });
});

describe("renderPreview", () => {
  it("posts the body with the design selector and returns an object URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["png-bytes"]),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { renderPreview } = await import("./calibrator");
    const url = await renderPreview(
      "flat-lay-01",
      { colour: "black", ...CONFIG },
      "bundled-on-dark",
    );

    expect(url).toBe("blob:mock-url");
    const [requestUrl, init] = must(fetchMock.mock.calls[0]);
    // `full` is the default: an explicit caller (the Preview tab) and an
    // absent one both mean "the size that is actually the output".
    expect(requestUrl).toBe("/api/templates/flat-lay-01/preview?scale=full");
    const body = JSON.parse(init.body as string);
    expect(body.design).toBe("bundled-on-dark");
    expect(body.colour).toBe("black");
  });

  it("asks for the editor size when told to", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["webp-bytes"]),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { renderPreview } = await import("./calibrator");
    await renderPreview("flat-lay-01", { colour: "black", ...CONFIG }, "bundled-grid", "editor");

    const [requestUrl] = must(fetchMock.mock.calls[0]);
    expect(requestUrl).toBe("/api/templates/flat-lay-01/preview?scale=editor");
  });

  it("throws CalibratorApiError when the preview request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    const { renderPreview, CalibratorApiError } = await import("./calibrator");
    await expect(renderPreview("flat-lay-01", { ...CONFIG })).rejects.toBeInstanceOf(
      CalibratorApiError,
    );
  });
});

describe("revision-aware mask saves", () => {
  it("serializes saves with the new revision and consumes each pending stroke once", async () => {
    let finish!: (response: Response) => void;
    let puts = 0;
    const { getTemplateConfig, saveTemplateConfig } = await answeringWith((request) => {
      if (request.method === "GET")
        return json(200, CONFIG, { ETag: "revision-1", "Last-Modified": SAVED_AT });
      puts += 1;
      return puts === 1
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : json(200, CONFIG, { ETag: "revision-3" });
    });
    await getTemplateConfig("race");
    const operation = {
      type: "stroke" as const,
      mode: "mask" as const,
      diameter_px: 12,
      points: [[5, 6] as [number, number]],
    };
    const edits = [{ placement_id: null, operations: [operation] }];
    const first = saveTemplateConfig("race", CONFIG, edits);
    const second = saveTemplateConfig("race", CONFIG, edits);
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    await Promise.resolve();
    expect(sent).toHaveLength(2);
    expect(await described(must(sent[1]))).toEqual({
      method: "PUT",
      path: "/api/templates/race/config",
      ifMatch: "revision-1",
      body: { request_id: expect.any(String), config: CONFIG, mask_edits: edits },
    });
    finish(json(200, CONFIG, { ETag: "revision-2" }));
    await first;
    await second;
    expect(sent).toHaveLength(3);
    expect(await described(must(sent[2]))).toEqual({
      method: "PUT",
      path: "/api/templates/race/config",
      ifMatch: "revision-2",
      body: { request_id: expect.any(String), config: CONFIG, mask_edits: [] },
    });
  });
});

describe("prepared revision refresh", () => {
  it.each(["original", "reordered"])(
    "accepts unchanged saved configuration with %s keys",
    async (order) => {
      const read =
        order === "reordered"
          ? { renderer: CONFIG.renderer, bounding_box: CONFIG.bounding_box, kind: CONFIG.kind }
          : CONFIG;
      const { refreshPreparedRevision, saveTemplateConfig } = await answeringWith((request) =>
        request.method === "GET"
          ? json(200, read, { ETag: '"sha256:baseline"' })
          : json(200, CONFIG, { ETag: '"sha256:saved"' }),
      );
      expect(await refreshPreparedRevision("fresh-baseline", CONFIG, "sha256:baseline")).toBe(true);
      await saveTemplateConfig("fresh-baseline", CONFIG);

      expect(sent).toHaveLength(2);
      expect(await described(must(sent[0]))).toMatchObject({
        method: "GET",
        path: "/api/templates/fresh-baseline/config",
      });
      expect(await described(must(sent[1]))).toEqual({
        method: "PUT",
        path: "/api/templates/fresh-baseline/config",
        ifMatch: '"sha256:baseline"',
        body: { request_id: expect.any(String), config: CONFIG, mask_edits: [] },
      });
    },
  );

  it.each(["revision", "configuration"])("refuses a newer external %s", async (changed) => {
    const { refreshPreparedRevision } = await answering(
      200,
      changed === "configuration" ? { ...CONFIG, kind: "single" } : CONFIG,
      { ETag: changed === "revision" ? '"sha256:external"' : '"sha256:completed"' },
    );

    expect(await refreshPreparedRevision("external-" + changed, CONFIG, "sha256:completed")).toBe(
      false,
    );
  });
});
