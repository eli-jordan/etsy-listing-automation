import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api/workspaceSettings";
import type { WorkspaceSettings } from "../../api/workspaceSettings";
import { SettingsPanel } from "./SettingsPanel";

const LIMITS = { scale: { min: 0.8, max: 1.1 }, offset: 0.1, rotation: 15 };
const WEIGHTS = {
  reviews: 30,
  favourites_per_day: 30,
  search_rank: 20,
  views_per_day: 10,
  shop_sales: 5,
  shop_rating: 5,
};
const initial = (
  template_positions: WorkspaceSettings["template_positions"] = LIMITS,
): WorkspaceSettings => ({
  revision: "s1",
  template_positions,
  concurrency: 1,
  providers: [{ name: "codex", enabled: true }],
  weights: WEIGHTS,
  default_weights: WEIGHTS,
  step_limit_minutes: 5,
  run_limit_minutes: 20,
});

beforeEach(() => {
  vi.spyOn(api, "getModelCatalogs").mockResolvedValue({ cache_seconds: 1800, providers: {} });
  vi.spyOn(api, "getSettings").mockResolvedValue(initial());
  // The server answers with what it wrote: the limits the page sent.
  vi.spyOn(api, "saveSettings").mockImplementation(async (_, changes) => ({
    kind: "saved",
    settings: {
      ...initial(changes.template_positions as WorkspaceSettings["template_positions"]),
      revision: "s2",
    },
  }));
  vi.spyOn(api, "getTemplatePositionImpact").mockResolvedValue({
    outside: [],
    templates_needing_inference: [],
  });
});
afterEach(() => vi.restoreAllMocks());

async function panel() {
  render(<SettingsPanel section="rendering" />);
  return screen.findByRole("region", { name: "Template positions" });
}

const largest = () => screen.getByRole("slider", { name: "Largest" });
const review = () => screen.getByRole("button", { name: "Review and save…" });
const discard = () => screen.getByRole("button", { name: "Discard" });

it("shows the saved limits as four sliders with the interactions' ranges", async () => {
  const region = await panel();
  const sliders = within(region).getAllByRole("slider");
  expect(
    sliders.map((s) => [
      s.getAttribute("aria-label"),
      s.getAttribute("min"),
      s.getAttribute("max"),
      s.getAttribute("step"),
      (s as HTMLInputElement).value,
    ]),
  ).toEqual([
    ["Smallest", "50", "100", "5", "80"],
    ["Largest", "100", "150", "5", "110"],
    ["Move", "0", "25", "1", "10"],
    ["Tilt", "0", "30", "1", "15"],
  ]);
  expect(review()).toBeDisabled();
  expect(discard()).toBeDisabled();
  expect(within(region).queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps edits as a draft that Discard reverts, never saving on blur", async () => {
  const region = await panel();
  fireEvent.change(largest(), { target: { value: "120" } });
  fireEvent.pointerUp(largest());
  fireEvent.blur(largest());
  expect(within(region).getByText("120%")).toBeInTheDocument();
  expect(within(region).getByRole("alert")).toHaveTextContent(/narrowing blocks any listing/);
  expect(review()).toBeEnabled();
  expect(api.saveSettings).not.toHaveBeenCalled();

  fireEvent.click(discard());
  expect(largest()).toHaveValue("110");
  expect(review()).toBeDisabled();
  expect(within(region).queryByRole("alert")).not.toBeInTheDocument();
});

it("confirms the change and the listings it blocks, then saves the whole section", async () => {
  vi.mocked(api.getTemplatePositionImpact).mockResolvedValue({
    outside: [{ listing: "frog-tee", positions: ["template_positions.front-flatlay"] }],
    templates_needing_inference: [],
  });
  await panel();
  fireEvent.change(largest(), { target: { value: "105" } });
  fireEvent.click(review());

  const dialog = await screen.findByRole("dialog", { name: "Save new limits?" });
  expect(api.getTemplatePositionImpact).toHaveBeenCalledWith({
    ...LIMITS,
    scale: { min: 0.8, max: 1.05 },
  });
  expect(dialog).toHaveTextContent("Largest: 110% → 105%");
  expect(await within(dialog).findByText(/frog-tee/)).toBeInTheDocument();
  expect(dialog).toHaveTextContent("they will block deploying until edited");
  expect(dialog).not.toHaveTextContent(/Marigold/);
  expect(api.saveSettings).not.toHaveBeenCalled();

  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(api.saveSettings).toHaveBeenCalledExactlyOnceWith("s1", {
    template_positions: { ...LIMITS, scale: { min: 0.8, max: 1.05 } },
  });
  expect(review()).toBeDisabled();
  expect(largest()).toHaveValue("105");
  // Review and save is disabled once saved, so focus lands on the panel title.
  expect(screen.getByRole("heading", { name: "Template positions" })).toHaveFocus();
});

it("says nothing else changes when no saved position falls outside", async () => {
  await panel();
  fireEvent.change(largest(), { target: { value: "120" } });
  fireEvent.click(review());
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("Nothing else changes.")).toBeInTheDocument();
  expect(dialog).toHaveTextContent("none fall outside the new limits");
});

it("names the Marigold templates that need inference when the read lists any", async () => {
  vi.mocked(api.getTemplatePositionImpact).mockResolvedValue({
    outside: [],
    templates_needing_inference: ["cc1717-folded", "cc1717-colour-pair"],
  });
  await panel();
  fireEvent.change(largest(), { target: { value: "120" } });
  fireEvent.click(review());
  const dialog = await screen.findByRole("dialog", { name: "Refit 2 Marigold templates?" });
  expect(dialog).toHaveTextContent("cc1717-folded and cc1717-colour-pair");
  expect(dialog).toHaveTextContent("once per template in the background");
  expect(within(dialog).getByRole("button", { name: "Save and refit" })).toBeEnabled();
});

it.each([
  [
    "Keep current limits",
    (dialog: HTMLElement) =>
      fireEvent.click(within(dialog).getByRole("button", { name: "Keep current limits" })),
  ],
  [
    "the close button",
    (dialog: HTMLElement) =>
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" })),
  ],
  ["Escape", () => fireEvent.keyDown(window, { key: "Escape" })],
  ["the backdrop", (dialog: HTMLElement) => fireEvent.click(dialog.parentElement as HTMLElement)],
])("%s cancels without saving and keeps the draft", async (_, close) => {
  await panel();
  fireEvent.change(largest(), { target: { value: "120" } });
  fireEvent.click(review());
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Nothing else changes.");
  close(dialog);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api.saveSettings).not.toHaveBeenCalled();
  expect(largest()).toHaveValue("120");
  await waitFor(() => expect(review()).toHaveFocus());
});

it("moves focus into the dialog and keeps Tab inside it", async () => {
  await panel();
  fireEvent.change(largest(), { target: { value: "120" } });
  fireEvent.click(review());
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Nothing else changes.");
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  for (let i = 0; i < 4; i += 1) {
    await userEvent.tab();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  }
});

it.each([
  [
    "a refusal",
    () =>
      vi.mocked(api.saveSettings).mockResolvedValue({
        kind: "invalid",
        message: "Not saved",
        fieldErrors: { "template_positions.scale.max": "must be at most 1.5" },
      }),
    "must be at most 1.5",
  ],
  [
    "a failed request",
    () => vi.mocked(api.saveSettings).mockRejectedValue(new Error("Could not save settings.yaml")),
    "Could not save settings.yaml",
  ],
])("keeps the dialog open with the error after %s", async (_, fail, message) => {
  fail();
  await panel();
  fireEvent.change(largest(), { target: { value: "120" } });
  fireEvent.click(review());
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Nothing else changes.");
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(largest()).toHaveValue("120");
});

it("still offers the save when the impact read fails, saying what it could not check", async () => {
  vi.mocked(api.getTemplatePositionImpact).mockRejectedValue(new Error("boom"));
  await panel();
  fireEvent.change(largest(), { target: { value: "120" } });
  fireEvent.click(review());
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText(/Could not check saved positions/)).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Save" })).toBeEnabled();
});
