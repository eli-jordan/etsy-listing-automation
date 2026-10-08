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
  const get = vi.spyOn(api, "getPreparation").mockImplementation((name) =>
    name === "first"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve({ ...READY, template: name }),
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
  const get = vi.spyOn(api, "getPreparation").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
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
