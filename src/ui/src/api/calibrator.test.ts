import { afterEach, describe, expect, it, vi } from "vitest";
import { must } from "../test/helpers";
import type { ColourMatrixTemplate } from "../types";

/** The generated client's requests, answered with real `Response`s. `api`
 * captures `fetch` and `Request` when it is created, so each test stubs them
 * and then imports a fresh copy. The base URL is relative (the SPA is served
 * by the API's own origin); jsdom has no origin for undici's `Request`, so the
 * stub resolves it against one. */
const sent: Request[] = [];

function answering(status: number, body: unknown, headers: Record<string, string> = {}) {
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
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json", ...headers },
      });
    }),
  );
  vi.resetModules();
  return import("./calibrator");
}

function onlyRequest(): Request {
  expect(sent).toHaveLength(1);
  return must(sent[0]);
}

const CONFIG: ColourMatrixTemplate = {
  kind: "colour-matrix",
  bounding_box: [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 0, y: 100 },
  ],
  displace: { enabled: false, strength: 0 },
  shade: { enabled: true, opacity: 0.6, blend: "soft-light" },
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
  it("PUTs the config as JSON to the named template and returns the saved one", async () => {
    const saved = { ...CONFIG, displace: { enabled: true, strength: 4 } };
    const { saveTemplateConfig } = await answering(200, saved);

    expect(await saveTemplateConfig("flat-lay-01", CONFIG)).toEqual(saved);
    const request = onlyRequest();
    expect(request.method).toBe("PUT");
    expect(new URL(request.url).pathname).toBe("/api/templates/flat-lay-01/config");
    expect(request.headers.get("Content-Type")).toBe("application/json");
    expect(await request.json()).toEqual(CONFIG);
  });

  it.each([404, 500])("throws CalibratorApiError on a %i", async (status) => {
    const { saveTemplateConfig, CalibratorApiError } = await answering(status, { detail: "bad" });

    await expect(saveTemplateConfig("flat-lay-01", CONFIG)).rejects.toBeInstanceOf(
      CalibratorApiError,
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
