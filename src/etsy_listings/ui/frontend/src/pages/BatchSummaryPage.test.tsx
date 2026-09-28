import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as batchesApi from "../api/batches";
import type { BatchDetail, BatchRow } from "../api/batches";
import { BatchSummaryPage } from "./BatchSummaryPage";

function row(name: string, over: Partial<BatchRow> = {}): BatchRow {
  return {
    id: name,
    sources: [`${name}.png`],
    name,
    design: name,
    creation: "created",
    error: null,
    ai: "queued",
    ai_steps: [],
    ai_error: null,
    queue_position: null,
    proposal: null,
    stale_reasons: [],
    ...over,
  };
}

function batch(rows: BatchRow[]): BatchDetail {
  return {
    id: "b1",
    label: "heavyweight-tee · 27 Sep 11:42",
    listing_template: "heavyweight-tee",
    created_at: "2026-09-27T11:42:00",
    rows,
    concurrency: 1,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/batches/b1"]}>
      <Routes>
        <Route path="/batches/:id" element={<BatchSummaryPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function rowFor(name: string): HTMLElement {
  const found = screen.getAllByText(name)[0]?.closest("tr");
  if (!found) throw new Error(`no row ${name}`);
  return found;
}

afterEach(() => vi.restoreAllMocks());

describe("BatchSummaryPage", () => {
  it("lists the names created with Open, and Retry on a failed row (UI doc §7)", async () => {
    const failed = row("cedar-trail-2", {
      creation: "failed",
      error: "Couldn't write cedar-trail-2.png: disk full. Fix that, then Retry.",
    });
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(
      batch([row("night-hike-club"), failed, row("lake-loop", { creation: "pending" })]),
    );
    const retry = vi
      .spyOn(batchesApi, "retryBatchRow")
      .mockResolvedValue(batch([row("night-hike-club"), row("cedar-trail-2"), row("lake-loop")]));
    renderPage();

    await screen.findByRole("heading", { name: "heavyweight-tee · 27 Sep 11:42" });
    expect(screen.getByText(/1 of 3 listings created/)).toBeInTheDocument();
    const created = within(rowFor("night-hike-club"));
    expect(created.getByText("Listing created")).toBeInTheDocument();
    expect(created.getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/listings/night-hike-club",
    );
    expect(within(rowFor("lake-loop")).getByText("Not created yet")).toBeInTheDocument();
    const broken = within(rowFor("cedar-trail-2"));
    expect(broken.getByText(/disk full/)).toBeInTheDocument();
    expect(broken.queryByRole("link", { name: "Open" })).toBeNull();

    fireEvent.click(broken.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(/3 of 3 listings created/)).toBeInTheDocument();
    expect(retry).toHaveBeenCalledWith("b1", "cedar-trail-2");
  });

  it("says a retry or a load that failed", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(
      batch([row("a", { creation: "failed", error: "nope" })]),
    );
    vi.spyOn(batchesApi, "retryBatchRow").mockRejectedValue(new Error("Retry failed."));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Retry failed.");
  });

  it("says a batch that does not exist", async () => {
    vi.spyOn(batchesApi, "getBatch").mockRejectedValue(new Error("No such batch."));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("No such batch.");
  });
});
