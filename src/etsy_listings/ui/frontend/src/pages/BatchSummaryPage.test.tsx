import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as batchesApi from "../api/batches";
import type { BatchDetail, BatchRow } from "../api/batches";
import type { WorkflowStep } from "../types";
import { BatchSummaryPage, POLL_MS } from "./BatchSummaryPage";

function row(name: string, over: Partial<BatchRow> = {}): BatchRow {
  return {
    id: name,
    sources: [`${name}.png`],
    name,
    design: name,
    creation: "created",
    error: null,
    ai: "done",
    ai_steps: [],
    ai_error: null,
    queue_position: null,
    proposal: null,
    stale_reasons: [],
    reviewed: false,
    reviewable: true,
    deleted: false,
    ...over,
  };
}

function steps(
  brief: WorkflowStep["state"],
  market: WorkflowStep["state"],
  seo: WorkflowStep["state"],
): WorkflowStep[] {
  return [
    { id: "brief", state: brief },
    { id: "market", state: market },
    { id: "seo", state: seo },
  ];
}

function batch(rows: BatchRow[], over: Partial<BatchDetail> = {}): BatchDetail {
  return {
    id: "b1",
    label: "heavyweight-tee · 27 Sep 11:42",
    listing_template: "heavyweight-tee",
    created_at: "2026-09-27T11:42:00",
    rows,
    concurrency: 1,
    status: "drafting",
    ...over,
  };
}

/** The `batch-summary` frame's rows, one per AI state. */
const MID_RUN = [
  row("night-hike-club", { proposal: "ready" }),
  row("after-rain-trail-2", { proposal: "stale", stale_reasons: ["brief edited since"] }),
  row("aurora-switchbacks", {
    ai: "running",
    ai_steps: steps("done", "active", "pending"),
    reviewable: false,
  }),
  row("lake-loop", { ai: "queued", queue_position: 1, reviewable: false }),
  row("pine-ridge-run", { ai: "queued", queue_position: 2, reviewable: false }),
  row("summit-coffee", {
    ai: "failed",
    ai_steps: steps("done", "failed", "pending"),
    ai_error: "Etsy market search failed: rate limit reached",
  }),
  row("trailhead-sunset", {
    creation: "failed",
    ai: null,
    error: "Couldn't write designs/trailhead-sunset.png: the disk is full. Free space, then Retry.",
    reviewable: false,
  }),
];

/** The frame's review column: one reviewed, one not, one deleted. */
const IN_REVIEW = [
  row("night-hike-club", { reviewed: true }),
  row("after-rain-trail-2", { proposal: "ready" }),
  row("old-mill-run", { ai: "cancelled", deleted: true, reviewable: false }),
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/batches/b1"]}>
      <Routes>
        <Route path="/batches/:id" element={<BatchSummaryPage />} />
        <Route path="/listing-templates" element={<p>Listing templates page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function rowFor(name: string): HTMLElement {
  const found = screen.getAllByText(name)[0]?.closest("tr");
  if (!found) throw new Error(`no row ${name}`);
  return found;
}

function counts(): string {
  return document.querySelector(".bc-counts")?.textContent ?? "";
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("BatchSummaryPage", () => {
  it("shows the queue mid-run: counts, each row's AI and its proposal (UI doc §7)", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(MID_RUN));
    renderPage();

    await screen.findByRole("heading", { name: "heavyweight-tee · 27 Sep 11:42" });
    expect(counts()).toContain("2 drafted");
    expect(counts()).toContain("1 drafting");
    expect(counts()).toContain("2 queued");
    expect(counts()).toContain("2 need retry");
    expect(screen.getByText(/Drafting one listing at a time/)).toBeInTheDocument();

    const done = within(rowFor("night-hike-club"));
    expect(done.getByText("Brief, market research and SEO done")).toBeInTheDocument();
    expect(done.getByText("Ready to review")).toBeInTheDocument();
    expect(
      within(rowFor("after-rain-trail-2")).getByText("Stale: brief edited since"),
    ).toBeVisible();
    expect(
      within(rowFor("aurora-switchbacks")).getByRole("status", {
        name: "AI Mode: Researching the market…",
      }),
    ).toBeInTheDocument();
    expect(within(rowFor("lake-loop")).getByText("Queued, next in line")).toBeInTheDocument();
    expect(within(rowFor("pine-ridge-run")).getByText("Queued, 2nd in line")).toBeInTheDocument();

    const failed = within(rowFor("summit-coffee"));
    expect(
      failed.getByRole("status", { name: "AI Mode: Market research failed" }),
    ).toBeInTheDocument();
    expect(failed.getByText(/rate limit reached/)).toBeInTheDocument();
    expect(failed.getByText(/The brief is saved; Retry reruns research and SEO/)).toBeVisible();
    expect(failed.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    const uncreated = within(rowFor("trailhead-sunset"));
    expect(uncreated.getByText(/the disk is full/)).toBeInTheDocument();
    expect(uncreated.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(uncreated.queryByRole("link", { name: "Open" })).toBeNull();
    expect(done.getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/listings/night-hike-club?batch=b1",
    );
  });

  it("retries one row, or every failed row at once", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(MID_RUN));
    const retryRow = vi
      .spyOn(batchesApi, "retryBatchRow")
      .mockResolvedValue(batch(MID_RUN.map((r) => ({ ...r, ai: "queued" as const }))));
    const control = vi.spyOn(batchesApi, "controlBatch").mockResolvedValue(batch(MID_RUN));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Retry 2 failed/ }));
    expect(control).toHaveBeenCalledWith("b1", "retry");

    fireEvent.click(within(rowFor("summit-coffee")).getByRole("button", { name: "Retry" }));
    expect(retryRow).toHaveBeenCalledWith("b1", "summit-coffee");
    await waitFor(() => expect(counts()).toContain("6 queued"));
  });

  it("cancels the batch, then offers Resume", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(MID_RUN));
    const stopped = MID_RUN.map((r) =>
      r.ai === "queued" ? { ...r, ai: "stopped" as const, queue_position: null } : r,
    ).map((r) => (r.ai === "running" ? { ...r, ai: "cancelled" as const } : r));
    const control = vi
      .spyOn(batchesApi, "controlBatch")
      .mockResolvedValueOnce(batch(stopped))
      .mockResolvedValueOnce(batch(MID_RUN));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Cancel batch" }));

    const resume = await screen.findByRole("button", { name: "Resume" });
    expect(control).toHaveBeenCalledWith("b1", "cancel");
    expect(within(rowFor("lake-loop")).getByText("Stopped. Resume queues it again.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Cancel batch" })).toBeNull();

    fireEvent.click(resume);

    expect(await screen.findByRole("button", { name: "Cancel batch" })).toBeInTheDocument();
    expect(control).toHaveBeenLastCalledWith("b1", "resume");
  });

  it("polls while a row is queued or running, and stops once none is", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const finished = batch(
      MID_RUN.map((r) => (r.creation === "created" ? { ...r, ai: "done" as const } : r)),
    );
    const load = vi
      .spyOn(batchesApi, "getBatch")
      .mockResolvedValueOnce(batch(MID_RUN))
      .mockResolvedValue(finished);
    renderPage();
    await waitFor(() => expect(counts()).toContain("1 drafting"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS);
    });
    await waitFor(() => expect(counts()).toContain("6 drafted"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    });

    expect(load).toHaveBeenCalledTimes(2);
  });

  it("says a retry or a load that failed", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(
      batch([row("a", { creation: "failed", ai: null, error: "nope" })]),
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

  it("says how drafting runs only while it is running", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(IN_REVIEW, { status: "in_review" }));
    renderPage();

    expect(await screen.findByText(/Drafting finished\./)).toBeInTheDocument();
    expect(screen.queryByText(/listing at a time/)).toBeNull();
    expect(screen.queryByText(/Work carries on if you close this tab/)).toBeNull();
  });

  it("says how many draft at once when the limit is above one", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(MID_RUN, { concurrency: 3 }));
    renderPage();

    expect(
      await screen.findByText(
        /Drafting up to 3 listings at a time\. Work carries on if you close this tab\./,
      ),
    ).toBeInTheDocument();
  });

  it("says drafting stopped while Cancel batch has left work for Resume", async () => {
    const stopped = IN_REVIEW.map((r) =>
      r.name === "after-rain-trail-2" ? { ...r, ai: "stopped" as const } : r,
    );
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(stopped, { status: "stopped" }));
    renderPage();

    expect(await screen.findByText(/Drafting stopped\. Resume queues the rest\./)).toBeVisible();
  });

  it("marks a row reviewed and back, and counts the reviewed listings", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(IN_REVIEW, { status: "in_review" }));
    const reviewed = IN_REVIEW.map((r) =>
      r.name === "after-rain-trail-2" ? { ...r, reviewed: true } : r,
    );
    const mark = vi
      .spyOn(batchesApi, "setReviewed")
      .mockResolvedValueOnce(batch(reviewed, { status: "complete" }))
      .mockResolvedValueOnce(batch(IN_REVIEW, { status: "in_review" }));
    renderPage();

    await waitFor(() => expect(counts()).toContain("1 of 2 reviewed"));
    fireEvent.click(
      within(rowFor("after-rain-trail-2")).getByRole("button", { name: "Mark reviewed" }),
    );

    await waitFor(() => expect(counts()).toContain("2 of 2 reviewed"));
    expect(mark).toHaveBeenCalledWith("b1", "after-rain-trail-2", true);
    const undo = within(rowFor("after-rain-trail-2")).getByRole("button", { name: /Reviewed/ });
    expect(undo).toHaveAttribute("title", "Mark needs review");
    fireEvent.click(undo);

    await waitFor(() => expect(counts()).toContain("1 of 2 reviewed"));
    expect(mark).toHaveBeenLastCalledWith("b1", "after-rain-trail-2", false);
  });

  it("offers Reviewed only on rows the seller can review (UI doc §7)", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(MID_RUN));
    renderPage();

    await screen.findAllByText("night-hike-club");
    for (const name of ["aurora-switchbacks", "lake-loop", "trailhead-sunset"]) {
      expect(within(rowFor(name)).queryByRole("button", { name: /reviewed/i })).toBeNull();
    }
    expect(
      within(rowFor("summit-coffee")).getByRole("button", { name: "Mark reviewed" }),
    ).toBeInTheDocument();
  });

  it("strikes a deleted listing's row through, with nothing to open", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(IN_REVIEW, { status: "in_review" }));
    renderPage();

    await screen.findByText("old-mill-run");
    const deleted = within(rowFor("old-mill-run"));
    expect(screen.getByText("old-mill-run").closest("s")).not.toBeNull();
    expect(deleted.getByText("Listing deleted. Its AI work was cancelled.")).toBeInTheDocument();
    expect(deleted.queryByRole("link")).toBeNull();
    expect(counts()).toContain("1 deleted");
  });

  it("shows a never-created row's kept upload as its thumbnail", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(MID_RUN));
    renderPage();

    await screen.findByText("trailhead-sunset");
    const thumb = rowFor("trailhead-sunset").querySelector("img");
    expect(thumb).toHaveAttribute("src", "/api/batches/b1/rows/trailhead-sunset/thumbnail");
  });

  it("renames the batch by double-clicking its label", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(IN_REVIEW));
    const rename = vi
      .spyOn(batchesApi, "renameBatch")
      .mockResolvedValue(batch(IN_REVIEW, { label: "Autumn trail drop" }));
    renderPage();

    fireEvent.doubleClick(
      await screen.findByRole("heading", { name: "heavyweight-tee · 27 Sep 11:42" }),
    );
    const field = screen.getByRole("textbox", { name: "Batch label" });
    fireEvent.change(field, { target: { value: "Autumn trail drop" } });
    fireEvent.keyDown(field, { key: "Enter" });

    expect(await screen.findByRole("heading", { name: "Autumn trail drop" })).toBeInTheDocument();
    expect(rename).toHaveBeenCalledWith("b1", "Autumn trail drop");
  });

  it("deletes the batch record after saying what stays, then returns to the templates", async () => {
    vi.spyOn(batchesApi, "getBatch").mockResolvedValue(batch(IN_REVIEW));
    const remove = vi.spyOn(batchesApi, "deleteBatch").mockResolvedValue();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Delete batch record" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/keeps every listing, design, brief and proposal/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete record" }));

    expect(await screen.findByText("Listing templates page")).toBeInTheDocument();
    expect(remove).toHaveBeenCalledWith("b1");
  });
});
