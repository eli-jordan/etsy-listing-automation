import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi, type MockInstance } from "vitest";
import * as api from "../../api/workspaceSettings";
import type { WorkspaceSettings, SettingsOutcome } from "../../api/workspaceSettings";
import { SettingsPanel } from "./SettingsPanel";

// ADR-0057 in the Admin page: the floor, the coupled saves and the notice.

const WEIGHTS = {
  reviews: 30,
  favourites_per_day: 30,
  search_rank: 20,
  views_per_day: 10,
  shop_sales: 5,
  shop_rating: 5,
};
const settings = (changes: Partial<WorkspaceSettings> = {}): WorkspaceSettings => ({
  revision: "s1",
  concurrency: 1,
  providers: [
    { name: "codex", enabled: true },
    { name: "claude", enabled: true },
    { name: "grok", enabled: true },
  ],
  weights: WEIGHTS,
  default_weights: WEIGHTS,
  step_limit_minutes: 5,
  run_limit_minutes: 20,
  ...changes,
});
const saved = (): SettingsOutcome => ({ kind: "saved", settings: settings({ revision: "s2" }) });

let save: MockInstance<typeof api.saveSettings>;
beforeEach(() => {
  vi.spyOn(api, "getModelCatalogs").mockResolvedValue({ cache_seconds: 1800, providers: {} });
  save = vi.spyOn(api, "saveSettings").mockResolvedValue(saved());
});
afterEach(() => vi.restoreAllMocks());

async function open(loaded = settings()) {
  vi.spyOn(api, "getSettings").mockResolvedValue(loaded);
  render(<SettingsPanel />);
  const section = await screen.findByRole("region", { name: "AI time limits" });
  return {
    section,
    step: within(section).getByRole("slider", { name: /Per step/ }),
    run: within(section).getByRole("slider", { name: /Whole run/ }),
  };
}

it("shows the saved limits with the run slider's minimum at the provider floor", async () => {
  const { section, step, run } = await open();

  expect(step).toHaveValue("5");
  expect(step).toHaveAttribute("min", "1");
  expect(step).toHaveAttribute("max", "15");
  expect(run).toHaveValue("20");
  expect(run).toHaveAttribute("min", "15");
  expect(run).toHaveAttribute("max", "60");
  expect(section).toHaveTextContent(
    "Minimum whole run: 15 minutes with 3 enabled providers × 5 minutes per step.",
  );
  expect(section).toHaveTextContent("Changes start with the next run.");
  expect(section).toHaveTextContent("Running jobs keep their current limit.");
});

it("raises the run limit with a larger step and saves both in one write", async () => {
  const { section, step, run } = await open();

  fireEvent.change(step, { target: { value: "10" } });
  expect(run).toHaveValue("30");
  expect(run).toHaveAttribute("min", "30");
  expect(within(section).getByRole("status", { name: "" })).toHaveTextContent(
    "Run limit increased from 20 to 30 minutes to allow 3 providers × 10 minutes.",
  );
  expect(save).not.toHaveBeenCalled();
  fireEvent.pointerUp(step);
  fireEvent.blur(step);

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save).toHaveBeenCalledWith("s1", { step_limit_minutes: 10, run_limit_minutes: 30 });
});

it("lowering the step relaxes the floor but keeps the seller's run limit", async () => {
  const { section, step, run } = await open(
    settings({ step_limit_minutes: 10, run_limit_minutes: 40 }),
  );

  fireEvent.change(step, { target: { value: "2" } });
  fireEvent.keyUp(step, { key: "ArrowLeft" });

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save).toHaveBeenCalledWith("s1", { step_limit_minutes: 2 });
  expect(run).toHaveValue("40");
  expect(run).toHaveAttribute("min", "6");
  expect(section).not.toHaveTextContent("Run limit increased");
});

it("never lets the run limit move below the floor", async () => {
  const { run } = await open();

  fireEvent.change(run, { target: { value: "8" } });
  fireEvent.pointerUp(run);

  expect(run).toHaveValue("15");
  await waitFor(() => expect(save).toHaveBeenCalledWith("s1", { run_limit_minutes: 15 }));
});

it("enabling a provider raises the run limit in the same save", async () => {
  const { section, run } = await open(
    settings({
      providers: [
        { name: "codex", enabled: true },
        { name: "claude", enabled: true },
        { name: "grok", enabled: false },
      ],
      step_limit_minutes: 10,
      run_limit_minutes: 20,
    }),
  );

  fireEvent.click(await screen.findByRole("button", { name: "Grok is off. Turn it on" }));

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  const changes = save.mock.lastCall?.[1] ?? {};
  expect(changes.run_limit_minutes).toBe(30);
  expect(changes.providers?.filter((p) => p.enabled)).toHaveLength(3);
  expect(run).toHaveValue("30");
  expect(run).toHaveAttribute("min", "30");
  expect(section).toHaveTextContent(
    "Run limit increased from 20 to 30 minutes because another provider is on.",
  );
});

it("turning a provider off leaves the run limit where the seller set it", async () => {
  const { section, run } = await open(settings({ step_limit_minutes: 5, run_limit_minutes: 15 }));

  fireEvent.click(await screen.findByRole("button", { name: "Grok is step 3. Turn it off" }));

  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.lastCall?.[1]).not.toHaveProperty("run_limit_minutes");
  expect(run).toHaveValue("15");
  expect(run).toHaveAttribute("min", "10");
  expect(section).toHaveTextContent("with 2 enabled providers × 5 minutes per step");
});

it("shows a refused limit next to the limits, naming the key", async () => {
  save.mockResolvedValue({
    kind: "invalid",
    message: "refused",
    fieldErrors: { "ai.run_limit_minutes": "must be at least 30" },
  });
  const { section, run } = await open();

  fireEvent.change(run, { target: { value: "25" } });
  fireEvent.pointerUp(run);

  expect(await within(section).findByRole("alert")).toHaveTextContent(
    "ai.run_limit_minutes: must be at least 30",
  );
});
