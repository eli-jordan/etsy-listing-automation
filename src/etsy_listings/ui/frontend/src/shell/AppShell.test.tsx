import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as listingsApi from "../api/listings";
import { AppShell } from "./AppShell";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<p>dashboard content</p>} />
          <Route path="/listings" element={<p>listings content</p>} />
          <Route path="/listings/:name" element={<p>editor content</p>} />
          <Route path="/templates" element={<p>templates content</p>} />
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
});

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

  it("marks Mockup Templates active on /templates", () => {
    renderAt("/templates");
    expect(screen.getByRole("link", { name: /Mockup Templates/ })).toHaveClass("nav-item--active");
  });
});
