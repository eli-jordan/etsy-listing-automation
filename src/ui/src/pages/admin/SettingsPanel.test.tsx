import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import * as api from "../../api/workspaceSettings";
import type { WorkspaceSettings, SettingsOutcome } from "../../api/workspaceSettings";
import { SettingsPanel } from "./SettingsPanel";

const DEFAULTS = {
  reviews: 30,
  favourites_per_day: 30,
  search_rank: 20,
  views_per_day: 10,
  shop_sales: 5,
  shop_rating: 5,
};
const initial = (weights = DEFAULTS): WorkspaceSettings => ({
  revision: "s1",
  concurrency: 1,
  providers: [
    { name: "codex", enabled: true },
    { name: "claude", enabled: true },
    { name: "grok", enabled: true },
  ],
  weights,
  default_weights: DEFAULTS,
  step_limit_minutes: 5,
  run_limit_minutes: 20,
});
const saved = (changes: Partial<WorkspaceSettings> = {}): SettingsOutcome => ({
  kind: "saved",
  settings: { ...initial(), revision: "s2", ...changes },
});

beforeEach(() => {
  vi.spyOn(api, "getModelCatalogs").mockResolvedValue({ cache_seconds: 1800, providers: {} });
  vi.spyOn(api, "getSettings").mockResolvedValue(initial());
  vi.spyOn(api, "saveSettings").mockResolvedValue(saved());
});
afterEach(() => vi.restoreAllMocks());

it("loads defaults without writing and saves a slider only once on completion", async () => {
  render(<SettingsPanel />);
  const slider = await screen.findByRole("slider", { name: "Listings drafted at once" });
  expect(slider).toHaveAttribute("min", "1");
  expect(slider).toHaveAttribute("max", "8");
  fireEvent.change(slider, { target: { value: "3" } });
  expect(api.saveSettings).not.toHaveBeenCalled();
  fireEvent.pointerUp(slider);
  fireEvent.blur(slider);
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledExactlyOnceWith("s1", { concurrency: 3 }),
  );
  expect(await screen.findByText("Saved")).toBeInTheDocument();
});

it("normalizes relative weights for display only and resets just weights", async () => {
  vi.mocked(api.getSettings).mockResolvedValue(
    initial({
      reviews: 1,
      favourites_per_day: 1,
      search_rank: 1,
      views_per_day: 1,
      shop_sales: 1,
      shop_rating: 0,
    }),
  );
  render(<SettingsPanel />);
  const market = await screen.findByRole("region", { name: "Market SEO scoring" });
  expect(within(market).getByText("Not counted")).toBeInTheDocument();
  expect(within(market).getAllByText("20%", { selector: ".sp-legend__pct" })).toHaveLength(5);
  expect(api.saveSettings).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledExactlyOnceWith("s1", { weights: DEFAULTS }),
  );
  expect(screen.getByRole("button", { name: "Reset to defaults" })).toBeDisabled();
});

it("moves a divider by keyboard and saves once with only adjacent shares changed", async () => {
  render(<SettingsPanel />);
  const divider = await screen.findByRole("separator", {
    name: "Between Reviews and Favourites per day",
  });
  fireEvent.keyDown(divider, { key: "ArrowRight", shiftKey: true });
  fireEvent.keyUp(divider, { key: "ArrowRight", shiftKey: true });
  fireEvent.blur(divider);
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledExactlyOnceWith("s1", {
      weights: { ...DEFAULTS, reviews: 35, favourites_per_day: 25 },
    }),
  );
  expect(divider).toHaveAttribute("aria-valuenow", "35");
});

it("drags adjacent shares, clamps at neighbors, and cancels an unfinished drag", async () => {
  render(<SettingsPanel />);
  const divider = await screen.findByRole("separator", {
    name: "Between Reviews and Favourites per day",
  });
  vi.spyOn(divider.parentElement as HTMLElement, "getBoundingClientRect").mockReturnValue({
    left: 0,
    width: 100,
  } as DOMRect);
  fireEvent.pointerDown(divider, { clientX: 30, pointerId: 1 });
  fireEvent.pointerMove(divider, { clientX: 90, pointerId: 1 });
  expect(divider).toHaveAttribute("aria-valuenow", "60");
  expect(api.saveSettings).not.toHaveBeenCalled();
  fireEvent.pointerUp(divider, { pointerId: 1 });
  fireEvent.lostPointerCapture(divider);
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledExactlyOnceWith("s1", {
      weights: { ...DEFAULTS, reviews: 60, favourites_per_day: 0 },
    }),
  );
  fireEvent.pointerDown(divider, { clientX: 60, pointerId: 2 });
  fireEvent.pointerMove(divider, { clientX: 10, pointerId: 2 });
  fireEvent.pointerCancel(divider, { pointerId: 2 });
  expect(divider).toHaveAttribute("aria-valuenow", "60");
  expect(api.saveSettings).toHaveBeenCalledTimes(1);
});

it.each([
  [
    -10,
    {
      reviews: 20,
      favourites_per_day: 10,
      search_rank: 0,
      views_per_day: 60,
      shop_sales: 5,
      shop_rating: 5,
    },
  ],
  [
    10,
    {
      reviews: 30,
      favourites_per_day: 0,
      search_rank: 10,
      views_per_day: 50,
      shop_sales: 5,
      shop_rating: 5,
    },
  ],
])("restores stacked zero shares in pointer direction %s", async (direction, expected) => {
  vi.mocked(api.getSettings).mockResolvedValue(
    initial({ ...DEFAULTS, favourites_per_day: 0, search_rank: 0, views_per_day: 60 }),
  );
  render(<SettingsPanel />);
  const dividers = await screen.findAllByRole("separator");
  expect(dividers).toHaveLength(5);
  expect(dividers.every((divider) => divider.tabIndex === 0)).toBe(true);
  const divider = screen.getByRole("separator", {
    name: "Between Favourites per day and Search rank",
  });
  vi.spyOn(divider.parentElement as HTMLElement, "getBoundingClientRect").mockReturnValue({
    left: 0,
    width: 100,
  } as DOMRect);
  fireEvent.pointerDown(divider, { clientX: 30, pointerId: 1 });
  fireEvent.pointerMove(divider, { clientX: 31, pointerId: 1 });
  expect(api.saveSettings).not.toHaveBeenCalled();
  fireEvent.pointerMove(divider, { clientX: 30 + direction, pointerId: 1 });
  fireEvent.pointerUp(divider, { pointerId: 1 });
  await waitFor(() =>
    expect(api.saveSettings).toHaveBeenCalledExactlyOnceWith("s1", { weights: expected }),
  );
});

it("serializes rapid saves with returned revisions and retains newer local values", async () => {
  let resolve!: (outcome: SettingsOutcome) => void;
  vi.mocked(api.saveSettings).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  render(<SettingsPanel />);
  const slider = await screen.findByRole("slider");
  fireEvent.change(slider, { target: { value: "2" } });
  fireEvent.keyUp(slider);
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(1));
  fireEvent.change(slider, { target: { value: "4" } });
  fireEvent.keyUp(slider);
  expect(api.saveSettings).toHaveBeenCalledTimes(1);
  await act(async () => resolve(saved({ concurrency: 2 })));
  await waitFor(() => expect(api.saveSettings).toHaveBeenLastCalledWith("s2", { concurrency: 4 }));
  expect(slider).toHaveValue("4");
});

it("stops queued saves after conflict until explicit reload discards stale edits", async () => {
  vi.mocked(api.saveSettings).mockResolvedValue({ kind: "conflict", message: "external edit" });
  render(<SettingsPanel />);
  const slider = await screen.findByRole("slider");
  fireEvent.change(slider, { target: { value: "2" } });
  fireEvent.keyUp(slider);
  fireEvent.change(slider, { target: { value: "4" } });
  fireEvent.keyUp(slider);
  expect(await screen.findByText(/Settings changed on disk/)).toBeInTheDocument();
  expect(slider).toBeDisabled();
  expect(screen.getAllByRole("separator").every((divider) => divider.tabIndex === -1)).toBe(true);
  expect(api.saveSettings).toHaveBeenCalledTimes(1);
  vi.mocked(api.getSettings).mockResolvedValue({
    ...initial(),
    revision: "external",
    concurrency: 3,
  });
  fireEvent.click(screen.getByRole("button", { name: "Reload settings" }));
  await waitFor(() => expect(screen.getByRole("slider")).toHaveValue("3"));
  expect(screen.getByRole("slider")).toBeEnabled();
  expect(api.saveSettings).toHaveBeenCalledTimes(1);
});

it("keeps invalid file errors visible through failed rechecks, without default controls", async () => {
  vi.mocked(api.getSettings).mockRejectedValue(
    new Error("settings.yaml: batch_ai.concurrency must be at least 1"),
  );
  render(<SettingsPanel />);
  expect(await screen.findByRole("alert")).toHaveTextContent("settings.yaml: batch_ai.concurrency");
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Check file again" }));
  await waitFor(() => expect(api.getSettings).toHaveBeenCalledTimes(2));
  expect(screen.getByRole("alert")).toHaveTextContent("settings.yaml");
});

it("reload discards a refused edit even when the external file returned to its original revision", async () => {
  vi.mocked(api.saveSettings).mockResolvedValue({ kind: "conflict", message: "changed" });
  render(<SettingsPanel />);
  const slider = await screen.findByRole("slider");
  fireEvent.change(slider, { target: { value: "4" } });
  fireEvent.keyUp(slider);
  fireEvent.click(await screen.findByRole("button", { name: "Reload settings" }));
  await waitFor(() => expect(screen.getByRole("slider")).toHaveValue("1"));
});

it("ignores an abandoned initial read when StrictMode starts a fresh read", async () => {
  let resolve!: (value: WorkspaceSettings) => void;
  vi.mocked(api.getSettings).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  render(
    <StrictMode>
      <SettingsPanel />
    </StrictMode>,
  );
  const slider = await screen.findByRole("slider");
  fireEvent.change(slider, { target: { value: "4" } });
  await act(async () => resolve(initial()));
  expect(screen.getByRole("slider")).toHaveValue("4");
});

it("retains refused field edits, keeps other controls usable, and retries network failures", async () => {
  vi.mocked(api.saveSettings).mockResolvedValueOnce({
    kind: "invalid",
    message: "bad concurrency",
    fieldErrors: { "batch_ai.concurrency": "Choose 1–8" },
  });
  render(<SettingsPanel />);
  const slider = await screen.findByRole("slider");
  fireEvent.change(slider, { target: { value: "3" } });
  fireEvent.blur(slider);
  expect(await screen.findByRole("alert")).toHaveTextContent("Choose 1–8");
  expect(slider).toHaveValue("3");
  expect(
    screen.getByRole("separator", { name: "Between Reviews and Favourites per day" }),
  ).toHaveAttribute("tabindex", "0");
  vi.mocked(api.saveSettings).mockRejectedValueOnce(new Error("network down"));
  fireEvent.click(screen.getByRole("button", { name: "Retry save" }));
  expect(await screen.findByText("network down")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry save" }));
  expect(await screen.findByText("Saved")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("serializes provider saves with other settings and keeps newer choices during responses", async () => {
  let resolve!: (value: SettingsOutcome) => void;
  vi.mocked(api.saveSettings).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  render(<SettingsPanel />);
  fireEvent.click(await screen.findByRole("button", { name: "Codex is step 1. Turn it off" }));
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Grok is step 2. Turn it off" }));
  expect(api.saveSettings).toHaveBeenCalledTimes(1);
  await act(async () => resolve(saved()));
  await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.saveSettings).mock.calls[1]?.[0]).toBe("s2");
  expect(vi.mocked(api.saveSettings).mock.calls[1]?.[1].providers).toEqual([
    { name: "codex", enabled: false },
    { name: "claude", enabled: true },
    { name: "grok", enabled: false },
  ]);
  expect(screen.getByRole("button", { name: "Grok is off. Turn it on" })).toBeInTheDocument();
});
