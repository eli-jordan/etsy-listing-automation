import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import * as api from "../api/preparation";
import { READY } from "../test/marigold";
import type { TemplateSummary } from "../types";
import { useTemplateReadiness } from "./useTemplateReadiness";

afterEach(() => vi.restoreAllMocks());
const row = (name: string): TemplateSummary => ({
  name,
  renderer: "marigold",
  kind: "single",
  colours: [],
  photos: [],
  has_config: true,
  status: "calibrated",
  status_reason: null,
});

it("discovers rail readiness sequentially and leaves the selected row to its editor", async () => {
  let finish!: (value: api.Preparation) => void;
  const pending = new Promise<api.Preparation>((resolve) => {
    finish = resolve;
  });
  const get = vi
    .spyOn(api, "getPreparation")
    .mockImplementation((name) =>
      name === "first" ? pending : Promise.resolve({ ...READY, template: name }),
    );
  const { result } = renderHook(() =>
    useTemplateReadiness([row("selected"), row("first"), row("next")], "selected", []),
  );
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  expect(get.mock.calls[0]?.[0]).toBe("first");
  expect(result.current).toEqual({});
  await act(async () => finish({ ...READY, template: "first" }));
  await waitFor(() => expect(result.current.next?.can_render).toBe(true));
  expect(get.mock.calls.map(([name]) => name)).toEqual(["first", "next"]);
});

it("aborts a stale discovery on template selection and ignores its late result", async () => {
  let finish!: (value: api.Preparation) => void;
  const pending = new Promise<api.Preparation>((resolve) => {
    finish = resolve;
  });
  const get = vi.spyOn(api, "getPreparation").mockReturnValue(pending);
  const { result, rerender } = renderHook(
    ({ selected }) => useTemplateReadiness([row("first")], selected, []),
    { initialProps: { selected: "other" } },
  );
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  const signal = get.mock.calls[0]?.[1];
  rerender({ selected: "first" });
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(READY));
  expect(result.current).toEqual({});
});

it("does not rediscover unrelated catalog rows for the selected editor's rebuild", async () => {
  const get = vi.spyOn(api, "getPreparation").mockResolvedValue(READY);
  const { rerender } = renderHook(
    ({ jobs }: { jobs: api.PreparationJob[] }) =>
      useTemplateReadiness([row("selected"), row("other")], "selected", jobs),
    { initialProps: { jobs: [] as api.PreparationJob[] } },
  );
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  await act(async () =>
    rerender({
      jobs: [{ template: "selected", id: "rebuild", phase: "running" } as api.PreparationJob],
    }),
  );
  expect(get).toHaveBeenCalledTimes(1);
  await act(async () => rerender({ jobs: [] }));
  expect(get).toHaveBeenCalledTimes(1);
});

it("refreshes only the background row whose job changed", async () => {
  const get = vi.spyOn(api, "getPreparation").mockResolvedValue(READY);
  const { rerender } = renderHook(
    ({ jobs }: { jobs: api.PreparationJob[] }) =>
      useTemplateReadiness([row("selected"), row("working"), row("idle")], "selected", jobs),
    { initialProps: { jobs: [] as api.PreparationJob[] } },
  );
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  await act(async () =>
    rerender({
      jobs: [{ template: "working", id: "rebuild", phase: "running" } as api.PreparationJob],
    }),
  );
  expect(get.mock.calls.map(([name]) => name)).toEqual(["working", "idle", "working"]);
});

it("rediscovers a template removed and later recreated with the same name", async () => {
  const get = vi.spyOn(api, "getPreparation").mockResolvedValue(READY);
  const { rerender } = renderHook(
    ({ templates }) => useTemplateReadiness(templates, "selected", []),
    { initialProps: { templates: [row("other")] } },
  );
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  rerender({ templates: [] });
  rerender({ templates: [row("other")] });
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
});

it("retries idle readiness after a changed job status request failed", async () => {
  const get = vi
    .spyOn(api, "getPreparation")
    .mockResolvedValueOnce(READY)
    .mockRejectedValueOnce(new Error("temporary failure"))
    .mockResolvedValue(READY);
  const { rerender } = renderHook(
    ({ jobs }: { jobs: api.PreparationJob[] }) =>
      useTemplateReadiness([row("other")], "selected", jobs),
    { initialProps: { jobs: [] as api.PreparationJob[] } },
  );
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  await act(async () =>
    rerender({ jobs: [{ template: "other", id: "job", phase: "running" } as api.PreparationJob] }),
  );
  await act(async () => rerender({ jobs: [] }));
  expect(get).toHaveBeenCalledTimes(3);
});
