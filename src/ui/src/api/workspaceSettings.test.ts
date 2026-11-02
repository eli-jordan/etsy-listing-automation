import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";
import { getModelCatalogs, getSettings, saveSettings } from "./workspaceSettings";

const answer = (status: number, data?: unknown, error?: unknown) =>
  ({ data, error, response: new Response(null, { status }) }) as never;
afterEach(() => vi.restoreAllMocks());

it("reads cached model lists or explicitly refreshes them without a settings patch", async () => {
  const get = vi
    .spyOn(api, "GET")
    .mockResolvedValue(answer(200, { providers: {}, cache_seconds: 1800 }));
  const patch = vi.spyOn(api, "PATCH");
  await getModelCatalogs();
  expect(get).toHaveBeenLastCalledWith("/api/admin/settings/models", {
    params: { query: { refresh: false } },
  });
  await getModelCatalogs(true);
  expect(get).toHaveBeenLastCalledWith("/api/admin/settings/models", {
    params: { query: { refresh: true } },
  });
  expect(patch).not.toHaveBeenCalled();
  get.mockResolvedValue(answer(500));
  await expect(getModelCatalogs()).rejects.toThrow("Saved choices are kept");
});

it("reads settings and retains the invalid file's explanation", async () => {
  vi.spyOn(api, "GET").mockResolvedValueOnce(answer(200, { revision: "s1" }));
  await expect(getSettings()).resolves.toEqual({ revision: "s1" });
  vi.mocked(api.GET).mockResolvedValueOnce(
    answer(422, undefined, { detail: "settings.yaml: bad key" }),
  );
  await expect(getSettings()).rejects.toThrow("settings.yaml: bad key");
  vi.mocked(api.GET).mockResolvedValueOnce(answer(500));
  await expect(getSettings()).rejects.toThrow("Could not read settings.yaml");
});

it("sends the file revision and changed keys and distinguishes save refusals", async () => {
  const patch = vi.spyOn(api, "PATCH").mockResolvedValueOnce(answer(200, { revision: "s2" }));
  await expect(saveSettings("s1", { concurrency: 2 })).resolves.toEqual({
    kind: "saved",
    settings: { revision: "s2" },
  });
  expect(patch).toHaveBeenCalledWith("/api/admin/settings", {
    body: { revision: "s1", changes: { concurrency: 2 } },
  });
  patch.mockResolvedValueOnce(answer(409, undefined, { kind: "conflict", message: "changed" }));
  await expect(saveSettings("s1", {})).resolves.toEqual({ kind: "conflict", message: "changed" });
  patch.mockResolvedValueOnce(
    answer(422, undefined, {
      kind: "invalid",
      message: "bad",
      field_errors: { "batch_ai.concurrency": "1–8" },
    }),
  );
  await expect(saveSettings("s1", {})).resolves.toEqual({
    kind: "invalid",
    message: "bad",
    fieldErrors: { "batch_ai.concurrency": "1–8" },
  });
  patch.mockResolvedValueOnce(answer(500));
  await expect(saveSettings("s1", {})).rejects.toThrow("Could not save settings.yaml");
});
