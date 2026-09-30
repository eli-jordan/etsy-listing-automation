import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import * as batchesApi from "../api/batches";
import type { BatchIndexEntry } from "../api/batches";
import { RecentBatches } from "./RecentBatches";

const TODAY = new Date();
const at = (daysAgo: number, hours = 11, minutes = 42) => {
  const when = new Date(TODAY);
  when.setDate(when.getDate() - daysAgo);
  when.setHours(hours, minutes, 0, 0);
  return when.toISOString();
};

function entry(over: Partial<BatchIndexEntry> & { id: string }): BatchIndexEntry {
  return {
    kind: "batch",
    label: over.id,
    listing_template: "heavyweight-tee",
    created_at: at(20),
    status: "in_review",
    designs: 0,
    listings: 0,
    drafted: 0,
    reviewed: 0,
    undrafted: 0,
    failures: 0,
    expires_at: null,
    ...over,
  };
}

/** The `templates` frame's five batches, one per status. */
const FRAME: BatchIndexEntry[] = [
  entry({
    id: "s1",
    kind: "staging",
    label: "everyday-tee · 26 Sep 16:05",
    listing_template: "everyday-tee",
    status: "staging",
    designs: 9,
    created_at: at(1),
    expires_at: "2026-10-03T16:05:00Z",
  }),
  entry({
    id: "b1",
    label: "heavyweight-tee · 27 Sep 11:42",
    status: "drafting",
    designs: 9,
    listings: 9,
    drafted: 5,
    reviewed: 2,
    failures: 2,
    created_at: at(0),
  }),
  entry({ id: "b2", label: "Autumn trail drop", listings: 8, reviewed: 5, failures: 1 }),
  entry({
    id: "b3",
    label: "Spring restock",
    status: "stopped",
    listings: 6,
    undrafted: 3,
    reviewed: 1,
  }),
  entry({ id: "b4", label: "everyday-tee · 19 Sep", status: "complete", listings: 6, reviewed: 6 }),
];

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderIt() {
  return render(
    <MemoryRouter initialEntries={["/listing-templates"]}>
      <Routes>
        <Route path="/listing-templates" element={<RecentBatches />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

function rowFor(label: string): HTMLElement {
  const found = screen.getByText(label).closest("tr");
  if (found === null) throw new Error(`no row ${label}`);
  return found;
}

afterEach(() => vi.restoreAllMocks());

describe("RecentBatches", () => {
  it("shows each batch's derived status and progress (UI doc §2)", async () => {
    vi.spyOn(batchesApi, "listBatches").mockResolvedValue(FRAME);
    renderIt();

    await screen.findByRole("heading", { name: "Recent batches" });

    const staging = within(rowFor("everyday-tee · 26 Sep 16:05"));
    expect(staging.getByText("Staging")).toBeInTheDocument();
    expect(staging.getByText("9 designs, not created yet · kept until 3 Oct")).toBeInTheDocument();
    expect(staging.getByText("Yesterday")).toBeInTheDocument();

    const drafting = within(rowFor("heavyweight-tee · 27 Sep 11:42"));
    expect(drafting.getByText("Drafting")).toBeInTheDocument();
    expect(drafting.getByText(/5 of 9 drafted · 2 of 9 reviewed/)).toBeInTheDocument();
    expect(drafting.getByText("2 need retry")).toBeInTheDocument();
    expect(drafting.getByText("Today 11:42")).toBeInTheDocument();

    const review = within(rowFor("Autumn trail drop"));
    expect(review.getByText("In review")).toBeInTheDocument();
    expect(review.getByText(/5 of 8 reviewed/)).toBeInTheDocument();
    expect(review.getByText("1 needs retry")).toBeInTheDocument();

    const stopped = within(rowFor("Spring restock"));
    expect(stopped.getByText("Stopped")).toBeInTheDocument();
    expect(
      stopped.getByText("Cancelled with 3 left to draft · 1 of 6 reviewed"),
    ).toBeInTheDocument();

    const complete = within(rowFor("everyday-tee · 19 Sep"));
    expect(complete.getByText("Complete")).toBeInTheDocument();
    expect(complete.getByText("6 of 6 reviewed")).toBeInTheDocument();
    expect(complete.queryByText(/retry/)).toBeNull();
  });

  it("opens staging for a staging row and the summary for a batch", async () => {
    vi.spyOn(batchesApi, "listBatches").mockResolvedValue(FRAME);
    renderIt();

    expect(
      await screen.findByRole("link", { name: "everyday-tee · 26 Sep 16:05" }),
    ).toHaveAttribute("href", "/batches/staging/s1");
    fireEvent.click(rowFor("Spring restock"));

    expect(screen.getByTestId("where")).toHaveTextContent("/batches/b3");
  });

  it("is absent while there is no batch", async () => {
    const load = vi.spyOn(batchesApi, "listBatches").mockResolvedValue([]);
    renderIt();

    await vi.waitFor(() => expect(load).toHaveBeenCalled());
    expect(screen.queryByRole("heading", { name: "Recent batches" })).toBeNull();
  });
});
