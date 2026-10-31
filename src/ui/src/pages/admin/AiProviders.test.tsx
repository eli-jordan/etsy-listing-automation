import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api/workspaceSettings";
import { AiProviders } from "./AiProviders";

beforeEach(() => {
  vi.spyOn(api, "getModelCatalogs").mockResolvedValue({
    cache_seconds: 1800,
    providers: {
      codex: {
        models: [{ id: "sol", label: "Sol", efforts: ["low", "high"] }],
        efforts: ["low", "high"],
      },
      claude: { models: [], efforts: ["high"] },
      grok: { models: [], efforts: ["high"] },
    },
  });
});
afterEach(() => vi.restoreAllMocks());

it("keeps omitted providers off, numbers enabled rows, guards the last toggle, and reorders by keyboard", async () => {
  const save = vi.fn();
  render(
    <AiProviders initial={[{ name: "claude", enabled: true }]} onSave={save} locked={false} />,
  );
  const off = await screen.findByRole("button", { name: "Codex is off. Turn it on" });
  fireEvent.click(screen.getByRole("button", { name: "Claude is step 1. Turn it off" }));
  expect(screen.getByText("At least one provider stays on")).toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(off);
  expect(screen.getByRole("button", { name: "Codex is step 2. Turn it off" })).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("button", { name: /Move Codex/ }), { key: "ArrowUp" });
  expect(save.mock.lastCall?.[0].map((p: { name: string }) => p.name)).toEqual([
    "codex",
    "claude",
    "grok",
  ]);
  expect(screen.getByRole("button", { name: "Codex is step 1. Turn it off" })).toBeInTheDocument();
});

it("retains stale model and effort, saves on blur once, and refreshes without saving", async () => {
  const save = vi.fn();
  render(
    <AiProviders
      initial={[{ name: "codex", enabled: true, model: "retired", effort: "extreme" }]}
      onSave={save}
      locked={false}
    />,
  );
  const model = await screen.findByRole("combobox", { name: "Codex model" });
  await screen.findByText(/retired is no longer offered/);
  expect(screen.getByText(/extreme is no longer offered/)).toBeInTheDocument();
  expect(model).toHaveValue("retired");
  fireEvent.change(model, { target: { value: "sol" } });
  expect(save).not.toHaveBeenCalled();
  fireEvent.blur(model);
  fireEvent.blur(model);
  expect(save).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("combobox", { name: "Codex reasoning" })).toHaveValue("extreme");
  fireEvent.click(screen.getByRole("button", { name: "Refresh lists" }));
  await waitFor(() => expect(api.getModelCatalogs).toHaveBeenLastCalledWith(true));
  expect(save).toHaveBeenCalledTimes(1);
});

it("retains saved choices through discovery failure, retries, and clears flags with Account default", async () => {
  vi.mocked(api.getModelCatalogs).mockRejectedValueOnce(new Error("offline"));
  const save = vi.fn();
  render(
    <AiProviders
      initial={[{ name: "codex", enabled: true, model: "saved", effort: "high" }]}
      onSave={save}
      locked={false}
    />,
  );
  await screen.findByText(/Model lists unavailable/);
  const model = screen.getByRole("combobox", { name: "Codex model" });
  expect(model).toHaveValue("saved");
  expect(screen.getByRole("combobox", { name: "Codex reasoning" })).toHaveValue("high");
  fireEvent.click(screen.getByRole("button", { name: "Refresh lists" }));
  await screen.findByText(/Model lists loaded/);
  expect(model).toHaveValue("saved");
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(model, { target: { value: "" } });
  fireEvent.blur(model);
  expect(save.mock.lastCall?.[0][0]).toEqual({ name: "codex", enabled: true, effort: "high" });
});

it("only drags from the handle, retains disabled choices, and avoids no-op reorder saves", async () => {
  const save = vi.fn();
  render(
    <AiProviders
      initial={[
        { name: "codex", enabled: true },
        { name: "grok", enabled: false, model: "saved", effort: "high" },
      ]}
      onSave={save}
      locked={false}
    />,
  );
  await screen.findByText(/Model lists loaded/);
  const handle = screen.getByRole("button", { name: /Move Grok/ });
  const target = screen.getByRole("button", { name: /Move Codex/ }).closest("li");
  if (!target) throw new Error("Codex row is missing");
  expect(target).not.toHaveAttribute("draggable");
  fireEvent.keyDown(screen.getByRole("button", { name: /Move Codex/ }), { key: "ArrowUp" });
  expect(save).not.toHaveBeenCalled();
  fireEvent.dragStart(handle, { dataTransfer: { setData: vi.fn() } });
  fireEvent.drop(target);
  expect(save.mock.lastCall?.[0][0]).toEqual({
    name: "grok",
    enabled: false,
    model: "saved",
    effort: "high",
  });
  fireEvent.click(screen.getByRole("button", { name: "Grok is off. Turn it on" }));
  expect(screen.getByRole("combobox", { name: "Grok model" })).toHaveValue("saved");
});
