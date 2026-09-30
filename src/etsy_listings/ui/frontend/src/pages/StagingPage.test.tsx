import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as batchesApi from "../api/batches";
import type { StagingDetail, StagingRow } from "../api/batches";
import { StagingPage } from "./StagingPage";

function row(over: Partial<StagingRow> & { id: string }): StagingRow {
  return {
    sources: [`${over.id}.png`],
    name: over.id,
    typed: false,
    state: "ready",
    message: null,
    note: null,
    suggestion: null,
    ...over,
  };
}

function session(rows: StagingRow[]): StagingDetail {
  return {
    id: "s1",
    listing_template: "heavyweight-tee",
    label: "heavyweight-tee · 27 Sep 11:42",
    template_saved_at: "2026-09-27T11:38:00",
    expires_at: "2026-10-04T11:42:00",
    rows,
  };
}

const READY = row({ id: "night-hike-club" });
const SUFFIXED = row({
  id: "r2",
  sources: ["after_rain_trail.png"],
  name: "after-rain-trail-2",
  note: "after-rain-trail is taken, so -2 was added",
});
const MERGED = row({
  id: "r3",
  sources: ["cedar-trail.png", "exports/cedar-trail copy.png"],
  name: "cedar-trail",
  note: "2 identical files, staged once: cedar-trail.png, exports/cedar-trail copy.png",
});
const INVALID = row({
  id: "r4",
  sources: ["sketch-draft.png"],
  name: "sketch-draft",
  state: "invalid",
  message: "sketch-draft.png has no alpha channel (mode 'RGB').",
});
const TAKEN = row({
  id: "r5",
  sources: ["moss and miles.png"],
  name: "take-a-hike",
  typed: true,
  state: "name",
  message: "take-a-hike is already a listing.",
  suggestion: "take-a-hike-2",
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/batches/staging/s1"]}>
      <Routes>
        <Route path="/batches/staging/:id" element={<StagingPage />} />
        <Route path="/batches/new" element={<p>new batch page</p>} />
        <Route path="/batches/:id" element={<p>summary page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("StagingPage", () => {
  it("counts the rows and creates only the ready ones (UI doc §5)", async () => {
    vi.spyOn(batchesApi, "getStaging").mockResolvedValue(
      session([READY, SUFFIXED, MERGED, INVALID]),
    );
    const confirm = vi
      .spyOn(batchesApi, "confirmStaging")
      .mockResolvedValue({ id: "s1" } as batchesApi.BatchDetail);
    renderPage();

    await screen.findByText("Review 4 designs");
    expect(screen.getByText("won't be created").parentElement).toHaveTextContent("1");
    expect(screen.getByText("duplicate merged").parentElement).toHaveTextContent("1");
    expect(screen.getByText(/after-rain-trail is taken, so -2 was added/)).toBeInTheDocument();
    expect(screen.getByText("Not created.")).toBeInTheDocument();
    expect(screen.getByText(/as saved at/)).toHaveTextContent("heavyweight-tee as saved at");
    expect(screen.getByText(/saved on the server until 4 Oct/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create 3 listings" }));
    await screen.findByText("summary page");
    expect(confirm).toHaveBeenCalledWith("s1");
  });

  it("says nothing about AI while it can run, and blocks Create when it cannot", async () => {
    vi.spyOn(batchesApi, "getStaging").mockResolvedValue({
      ...session([READY]),
      ai_blocked: {
        message: "No AI provider is ready.",
        remedy: "Add one in Setup, then come back. Your staging is kept.",
      },
    });
    renderPage();

    const create = await screen.findByRole("button", { name: "Create 1 listing" });
    expect(create).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "AI drafting can't run yet. No AI provider is ready. Add one in Setup, then come back. " +
        "Your staging is kept.",
    );
  });

  it("blocks Create on a name to fix, and Use suggestion sends it", async () => {
    vi.spyOn(batchesApi, "getStaging").mockResolvedValue(session([READY, TAKEN]));
    const patch = vi
      .spyOn(batchesApi, "patchStaging")
      .mockResolvedValue(session([READY, { ...TAKEN, name: "take-a-hike-2", state: "ready" }]));
    renderPage();

    const create = await screen.findByRole("button", { name: "Create 2 listings" });
    expect(create).toBeDisabled();
    expect(screen.getByText("Fix 1 name to create the listings.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Use take-a-hike-2" }));

    await waitFor(() => expect(create).toBeEnabled());
    expect(patch).toHaveBeenCalledWith("s1", { names: { r5: "take-a-hike-2" } });
    expect(screen.getByLabelText("Listing name for moss and miles.png")).toHaveValue(
      "take-a-hike-2",
    );
  });

  it("sends a typed name, a label and a removal only when committed", async () => {
    vi.spyOn(batchesApi, "getStaging").mockResolvedValue(session([READY, SUFFIXED]));
    const patch = vi.spyOn(batchesApi, "patchStaging").mockResolvedValue(session([READY]));
    renderPage();

    const name = await screen.findByLabelText("Listing name for night-hike-club.png");
    fireEvent.blur(name);
    expect(patch).not.toHaveBeenCalled();
    fireEvent.change(name, { target: { value: "night-club" } });
    fireEvent.keyDown(name, { key: "Enter" });
    fireEvent.blur(name);
    expect(patch).toHaveBeenCalledWith("s1", { names: { "night-hike-club": "night-club" } });

    const label = screen.getByLabelText("Batch label");
    fireEvent.change(label, { target: { value: "Autumn drop" } });
    fireEvent.blur(label);
    expect(patch).toHaveBeenCalledWith("s1", { label: "Autumn drop" });

    fireEvent.click(screen.getByRole("button", { name: "Remove after_rain_trail.png" }));
    expect(patch).toHaveBeenCalledWith("s1", { remove: ["r2"] });
  });

  it("cancel discards the session and returns to New batch", async () => {
    vi.spyOn(batchesApi, "getStaging").mockResolvedValue(session([READY]));
    const cancel = vi.spyOn(batchesApi, "cancelStaging").mockResolvedValue();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Cancel staging" }));

    await screen.findByText("new batch page");
    expect(cancel).toHaveBeenCalledWith("s1");
  });

  it("shows why a confirm or a load was refused", async () => {
    vi.spyOn(batchesApi, "getStaging").mockResolvedValue(session([READY]));
    vi.spyOn(batchesApi, "confirmStaging").mockRejectedValue(new Error("can no longer make"));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Create 1 listing" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("can no longer make");
  });

  it("says a session that has gone has gone", async () => {
    vi.spyOn(batchesApi, "getStaging").mockRejectedValue(new Error("This staging has gone."));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("This staging has gone.");
  });
});
