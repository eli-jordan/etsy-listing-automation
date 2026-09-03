import { afterEach, describe, expect, it, vi } from "vitest";
import { must } from "../test/helpers";
import type { ColourMatrixTemplate } from "../types";

vi.mock("./client", () => ({
  api: { GET: vi.fn(), PUT: vi.fn() },
}));

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

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("listTemplates", () => {
  it("returns the data on success", async () => {
    const { api } = await import("./client");
    vi.mocked(api.GET).mockResolvedValue({ data: [{ name: "a" }], error: undefined } as never);
    const { listTemplates } = await import("./calibrator");
    expect(await listTemplates()).toEqual([{ name: "a" }]);
  });

  it("throws CalibratorApiError on failure", async () => {
    const { api } = await import("./client");
    vi.mocked(api.GET).mockResolvedValue({ data: undefined, error: "boom" } as never);
    const { listTemplates, CalibratorApiError } = await import("./calibrator");
    await expect(listTemplates()).rejects.toBeInstanceOf(CalibratorApiError);
  });
});

describe("getTemplateConfig", () => {
  it("returns null on a 404 (no template.yaml yet)", async () => {
    const { api } = await import("./client");
    vi.mocked(api.GET).mockResolvedValue({ data: undefined, error: "not found" } as never);
    const { getTemplateConfig } = await import("./calibrator");
    expect(await getTemplateConfig("brand-new")).toBeNull();
  });

  it("returns the config on success", async () => {
    const { api } = await import("./client");
    vi.mocked(api.GET).mockResolvedValue({ data: CONFIG, error: undefined } as never);
    const { getTemplateConfig } = await import("./calibrator");
    expect(await getTemplateConfig("flat-lay-01")).toEqual(CONFIG);
  });
});

describe("saveTemplateConfig", () => {
  it("returns the saved config on success", async () => {
    const { api } = await import("./client");
    vi.mocked(api.PUT).mockResolvedValue({ data: CONFIG, error: undefined } as never);
    const { saveTemplateConfig } = await import("./calibrator");
    expect(await saveTemplateConfig("flat-lay-01", CONFIG)).toEqual(CONFIG);
  });

  it("throws CalibratorApiError on failure", async () => {
    const { api } = await import("./client");
    vi.mocked(api.PUT).mockResolvedValue({ data: undefined, error: "bad" } as never);
    const { saveTemplateConfig, CalibratorApiError } = await import("./calibrator");
    await expect(saveTemplateConfig("flat-lay-01", CONFIG)).rejects.toBeInstanceOf(
      CalibratorApiError,
    );
  });
});

describe("uploadTemplate", () => {
  it("posts a multipart form with the repeated files field and query params", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ name: "flat-lay-02", kind: "colour-matrix", colours: ["black"] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { uploadTemplate } = await import("./calibrator");
    const file = new File(["x"], "black.png", { type: "image/png" });
    const result = await uploadTemplate("flat-lay-02", "colour-matrix", [file]);

    expect(result.name).toBe("flat-lay-02");
    const [url, init] = must(fetchMock.mock.calls[0]);
    expect(url).toContain("name=flat-lay-02");
    expect(url).toContain("kind=colour-matrix");
    expect(init.method).toBe("POST");
    expect((init.body as FormData).getAll("files")).toEqual([file]);
  });

  it("throws CalibratorApiError when the upload fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    const { uploadTemplate, CalibratorApiError } = await import("./calibrator");
    await expect(uploadTemplate("x", "single", [new File(["x"], "a.png")])).rejects.toBeInstanceOf(
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
    expect(requestUrl).toBe("/api/templates/flat-lay-01/preview");
    const body = JSON.parse(init.body as string);
    expect(body.design).toBe("bundled-on-dark");
    expect(body.colour).toBe("black");
  });

  it("throws CalibratorApiError when the preview request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    const { renderPreview, CalibratorApiError } = await import("./calibrator");
    await expect(renderPreview("flat-lay-01", { ...CONFIG })).rejects.toBeInstanceOf(
      CalibratorApiError,
    );
  });
});
