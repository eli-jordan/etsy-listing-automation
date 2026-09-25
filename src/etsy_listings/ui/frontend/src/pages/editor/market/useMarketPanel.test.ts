import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, type MockInstance, vi } from "vitest";
import * as marketApi from "../../../api/market";
import { MARKET_QUERIES, marketSnapshot } from "../../../test/market";
import type { MarketSnapshot, WorkflowStep } from "../../../types";
import { type MarketRun, useMarketPanel } from "./useMarketPanel";

/** Which state the top listings panel is in (docs/ui-market-seo-interactions.md,
 * *Panel states*): from the AI run's market node, its `queries` and `market`
 * events, and the snapshot `GET …/market` answers on mount. */

let get: MockInstance<typeof marketApi.getMarketSnapshot>;

beforeEach(() => {
  get = vi.spyOn(marketApi, "getMarketSnapshot").mockResolvedValue(null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function run(
  market: WorkflowStep["state"] | null,
  over: Partial<MarketRun> & { detail?: string } = {},
): MarketRun {
  return {
    busy: false,
    steps:
      market === null
        ? []
        : [
            { id: "brief", state: "skipped", detail: null },
            { id: "market", state: market, detail: over.detail ?? null },
            { id: "seo", state: "pending", detail: null },
          ],
    queries: null,
    market: null,
    ...over,
  };
}

function panel(name: string, initial: MarketRun) {
  return renderHook(({ name, run }) => useMarketPanel(name, run), {
    initialProps: { name, run: initial },
  });
}

it("renders nothing before the first search and without a run", async () => {
  const { result } = panel("take-a-hike", run(null));

  await waitFor(() => expect(get).toHaveBeenCalledWith("take-a-hike"));
  expect(result.current).toBeNull();
});

it("shows the snapshot the last search saved", async () => {
  const saved = marketSnapshot();
  get.mockResolvedValue(saved);

  const { result } = panel("take-a-hike", run(null));

  await waitFor(() => expect(result.current).toEqual({ kind: "ready", snapshot: saved }));
});

it("shows a saved search that found nothing as the empty note", async () => {
  get.mockResolvedValue(marketSnapshot({ scored: 0, listings: [] }));

  const { result } = panel("take-a-hike", run(null));

  await waitFor(() => expect(result.current).toEqual({ kind: "empty", queries: MARKET_QUERIES }));
});

it("drops to loading as soon as research starts, even over a saved snapshot", async () => {
  get.mockResolvedValue(marketSnapshot());
  const { result, rerender } = panel("take-a-hike", run(null));
  await waitFor(() => expect(result.current?.kind).toBe("ready"));

  rerender({ name: "take-a-hike", run: run("active", { busy: true }) });
  expect(result.current).toEqual({ kind: "loading", queries: null });

  rerender({ name: "take-a-hike", run: run("active", { busy: true, queries: MARKET_QUERIES }) });
  expect(result.current).toEqual({ kind: "loading", queries: MARKET_QUERIES });
});

it("shows what the run found once its market event arrives", async () => {
  const found = marketSnapshot({ found: 7 });
  const { result, rerender } = panel("take-a-hike", run("active", { busy: true }));
  await waitFor(() => expect(get).toHaveBeenCalled());

  rerender({ name: "take-a-hike", run: run("done", { busy: true, market: found }) });

  expect(result.current).toEqual({ kind: "ready", snapshot: found });
});

it("keeps showing the newest search when the next run starts", async () => {
  const older = marketSnapshot({ found: 1 });
  const newer = marketSnapshot({ found: 2 });
  get.mockResolvedValue(older);
  const { result, rerender } = panel("take-a-hike", run(null));
  await waitFor(() => expect(result.current).toEqual({ kind: "ready", snapshot: older }));

  rerender({ name: "take-a-hike", run: run("done", { market: newer }) });
  expect(result.current).toEqual({ kind: "ready", snapshot: newer });

  // A new run starts from a clean view: no market yet, the node pending.
  rerender({ name: "take-a-hike", run: run("pending", { busy: true }) });
  expect(result.current).toEqual({ kind: "ready", snapshot: newer });
});

it("shows the empty note when the run found nothing comparable", async () => {
  const nothing: MarketSnapshot = marketSnapshot({ scored: 0, listings: [] });
  const { result, rerender } = panel("take-a-hike", run(null));
  await waitFor(() => expect(get).toHaveBeenCalled());

  rerender({ name: "take-a-hike", run: run("warning", { market: nothing }) });

  expect(result.current).toEqual({ kind: "empty", queries: MARKET_QUERIES });
});

it("shows a failure it watched happen, with the spec's reason", async () => {
  get.mockResolvedValue(marketSnapshot());
  const { result, rerender } = panel("take-a-hike", run("active", { busy: true }));
  await waitFor(() => expect(get).toHaveBeenCalled());

  rerender({
    name: "take-a-hike",
    run: run("failed", {
      detail: "Etsy market search failed: Etsy did not respond (HTTP 503) after 3 retries.",
    }),
  });

  expect(result.current).toEqual({
    kind: "failed",
    reason: "Etsy did not respond (HTTP 503) after 3 retries.",
  });
});

it("keeps a failure's own words when they are not a search failure", async () => {
  const { result, rerender } = panel("take-a-hike", run("active", { busy: true }));
  await waitFor(() => expect(get).toHaveBeenCalled());

  rerender({
    name: "take-a-hike",
    run: run("failed", { detail: "The AI run took longer than 3 minutes, so it was stopped." }),
  });

  expect(result.current).toEqual({
    kind: "failed",
    reason: "The AI run took longer than 3 minutes, so it was stopped.",
  });
});

it("returns to the saved snapshot after a reload, when the failure is only replayed", async () => {
  const saved = marketSnapshot();
  get.mockResolvedValue(saved);

  const { result } = panel(
    "take-a-hike",
    run("failed", { detail: "Etsy market search failed: HTTP 503" }),
  );

  await waitFor(() => expect(result.current).toEqual({ kind: "ready", snapshot: saved }));
});

it("reads the new listing's snapshot after a rename, and ignores a late answer", async () => {
  const first = marketSnapshot({ found: 1 });
  const second = marketSnapshot({ found: 2 });
  let answerFirst: (s: MarketSnapshot) => void = () => {};
  get.mockImplementation((name) =>
    name === "take-a-hike"
      ? new Promise((resolve) => (answerFirst = resolve))
      : Promise.resolve(second),
  );
  const { result, rerender } = panel("take-a-hike", run(null));

  rerender({ name: "take-a-trail", run: run(null) });
  await waitFor(() => expect(result.current).toEqual({ kind: "ready", snapshot: second }));
  answerFirst(first);
  await Promise.resolve();

  expect(result.current).toEqual({ kind: "ready", snapshot: second });
});

it("asks nothing for a listing that has no name yet", () => {
  const { result } = panel("", run(null));

  expect(get).not.toHaveBeenCalled();
  expect(result.current).toBeNull();
});

it("shows nothing when the snapshot cannot be read", async () => {
  get.mockRejectedValue(new marketApi.MarketApiError("boom"));

  const { result } = panel("take-a-hike", run(null));

  await waitFor(() => expect(get).toHaveBeenCalled());
  expect(result.current).toBeNull();
});
