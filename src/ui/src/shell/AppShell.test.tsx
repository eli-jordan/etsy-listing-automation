import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as backupApi from "../api/backup";
import type { BackupStatus } from "../api/backup";
import * as listingsApi from "../api/listings";
import { backupsOn, backupWarning } from "../test/backup";
import { deferred } from "../test/helpers";
import { AppShell } from "./AppShell";
import { FAST_POLL_MS, SLOW_POLL_MS } from "./backupStatus";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<p>dashboard content</p>} />
          <Route path="/listings" element={<p>listings content</p>} />
          <Route path="/listings/:name" element={<p>editor content</p>} />
          <Route path="/templates" element={<p>templates content</p>} />
          <Route path="/listing-templates" element={<p>listing templates content</p>} />
          <Route path="/listing-templates/new" element={<p>new listing template</p>} />
          <Route path="/admin" element={<p>admin content</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.spyOn(listingsApi, "getWorkspace").mockResolvedValue({
    shop_name: null,
    storage_id: "workspace-1",
  });
  vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(HEALTHY);
});

const HEALTHY = backupsOn();
const FAILING = backupsOn({ warnings: [backupWarning("failed")] });

afterEach(() => vi.restoreAllMocks());

describe("AppShell", () => {
  it("names the shop this workspace is for", async () => {
    /* One workspace is one shop, and the difference between the test shop and
       the real one is worth seeing before an edit, not after an apply. */
    vi.spyOn(listingsApi, "getWorkspace").mockResolvedValue({
      shop_name: "TakeAHikeTees",
      storage_id: "workspace-1",
    });
    renderAt("/");

    await waitFor(() => expect(screen.getByText("TakeAHikeTees")).toBeInTheDocument());
  });

  it("says nothing rather than guessing when the shop has no name yet", async () => {
    renderAt("/");
    await waitFor(() => expect(screen.getByText("dashboard content")).toBeInTheDocument());
    expect(screen.queryByText(/shop/i)).not.toBeInTheDocument();
  });

  it("says nothing, and shows no error, when the shop's name cannot be read", async () => {
    vi.spyOn(listingsApi, "getWorkspace").mockRejectedValue(new Error("offline"));
    renderAt("/");
    await waitFor(() => expect(screen.getByText("dashboard content")).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/offline|shop/i)).not.toBeInTheDocument();
  });

  it("renders the nav items", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: /Dashboard/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Listings/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Mockup Templates/ })).toBeInTheDocument();
  });

  it("renders the routed page content in the main area", () => {
    renderAt("/listings");
    expect(screen.getByText("listings content")).toBeInTheDocument();
  });

  it("marks Dashboard active only at the root path", () => {
    renderAt("/listings");
    expect(screen.getByRole("link", { name: /Dashboard/ })).not.toHaveClass("nav-item--active");
    expect(screen.getByRole("link", { name: /Listings/ })).toHaveClass("nav-item--active");
  });

  it("keeps Listings active while inside the editor", () => {
    renderAt("/listings/take-a-hike");
    expect(screen.getByRole("link", { name: /Listings/ })).toHaveClass("nav-item--active");
    expect(screen.getByText("editor content")).toBeInTheDocument();
  });

  it("puts Listing Templates between Listings and Mockup Templates", () => {
    renderAt("/");
    const names = screen.getAllByRole("link").map((link) => link.textContent);
    expect(names).toEqual([
      "Dashboard",
      "Listings",
      "Listing Templates",
      "Mockup Templates",
      "Admin",
    ]);
  });

  it("keeps Listing Templates, and only it, active while naming a new one", () => {
    renderAt("/listing-templates/new");
    expect(screen.getByRole("link", { name: /Listing Templates/ })).toHaveClass("nav-item--active");
    expect(screen.getByRole("link", { name: /^Listings$/ })).not.toHaveClass("nav-item--active");
    expect(screen.getByRole("link", { name: /Mockup Templates/ })).not.toHaveClass(
      "nav-item--active",
    );
  });

  it("marks Mockup Templates active on /templates", () => {
    renderAt("/templates");
    expect(screen.getByRole("link", { name: /Mockup Templates/ })).toHaveClass("nav-item--active");
  });

  it("replaces the Setup placeholder with Admin at /admin", () => {
    /* Admin plan, PR 3: the sidebar's bottom entry opens /admin. */
    renderAt("/admin");
    const admin = screen.getByRole("link", { name: "Admin" });
    expect(admin).toHaveAttribute("href", "/admin");
    expect(admin).toHaveClass("nav-item--active");
    expect(screen.getByText("admin content")).toBeInTheDocument();
    expect(screen.queryByText("Setup")).not.toBeInTheDocument();
  });
});

/** Resolves once the provider polls fast. The fast interval is armed only
 * when its effect re-runs on the applied status, and that re-run reads the
 * status at once: a second call proves it, where the first does not. */
async function untilFastPolling(status: { mock: { calls: unknown[] } }) {
  await waitFor(() => expect(status.mock.calls.length).toBeGreaterThanOrEqual(2));
}

describe("AppShell backup warning", () => {
  it("shows the warning above the page, with Open Backup, and a dot on Admin", async () => {
    vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(FAILING);
    renderAt("/listings");

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Backups need attention.");
    expect(banner).toHaveTextContent("The last backup failed: disk full");
    expect(screen.getByRole("link", { name: "Open Backup" })).toHaveAttribute(
      "href",
      "/admin?section=backup",
    );
    expect(screen.getByRole("img", { name: "Backups need attention" })).toBeInTheDocument();
    expect(screen.getByText("listings content")).toBeInTheDocument();
  });

  it("keeps the dot but not the banner on Admin, which has its own warnings", async () => {
    vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(FAILING);
    renderAt("/admin");

    expect(await screen.findByRole("img", { name: "Backups need attention" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the banner when the problem does", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const status = vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(FAILING);
      renderAt("/");
      await screen.findByRole("alert");
      status.mockResolvedValue(HEALTHY);
      await vi.advanceTimersByTimeAsync(SLOW_POLL_MS);
      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the latest warning when an older poll answers late", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const stale = deferred<BackupStatus>();
      vi.spyOn(backupApi, "getBackupStatus")
        .mockResolvedValue(FAILING)
        .mockReturnValueOnce(stale.promise);
      renderAt("/");
      await act(() => vi.advanceTimersByTimeAsync(SLOW_POLL_MS));
      await screen.findByRole("alert");

      await act(async () => stale.resolve(HEALTHY));

      expect(screen.getByRole("alert")).toHaveTextContent("disk full");
    } finally {
      vi.useRealTimers();
    }
  });

  it("polls faster while a backup runs, and stops while the tab is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      const running: BackupStatus = {
        ...HEALTHY,
        running: { operation: "backup", started_at: "2026-11-23T10:00:00Z", step: "backing_up" },
      };
      const status = vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(running);
      renderAt("/");
      await untilFastPolling(status);
      const before = status.mock.calls.length;
      await vi.advanceTimersByTimeAsync(FAST_POLL_MS * 2);
      expect(status.mock.calls.length).toBeGreaterThanOrEqual(before + 2);

      visibility.mockReturnValue("hidden");
      act(() => void document.dispatchEvent(new Event("visibilitychange")));
      const hidden = status.mock.calls.length;
      await vi.advanceTimersByTimeAsync(SLOW_POLL_MS * 2);
      expect(status.mock.calls).toHaveLength(hidden);
    } finally {
      vi.useRealTimers();
    }
  });

  it("polls faster while a restore runs", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      const restoring: BackupStatus = {
        ...HEALTHY,
        restore: {
          snapshot_id: "b".repeat(64),
          snapshot_time: "2026-11-23T08:00:00Z",
          target: "D:/restored",
          started_at: "2026-11-23T10:00:00Z",
          outcome: "running",
          fraction: 0.1,
        },
      };
      const status = vi.spyOn(backupApi, "getBackupStatus").mockResolvedValue(restoring);
      renderAt("/");
      await untilFastPolling(status);
      const before = status.mock.calls.length;
      await vi.advanceTimersByTimeAsync(FAST_POLL_MS * 2);
      expect(status.mock.calls.length).toBeGreaterThanOrEqual(before + 2);
    } finally {
      vi.useRealTimers();
    }
  });
});
