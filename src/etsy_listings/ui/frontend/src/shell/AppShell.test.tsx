import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

describe("AppShell", () => {
  it("renders the nav items", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: /Dashboard/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Listings/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Mockup templates/ })).toBeInTheDocument();
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

  it("marks Mockup templates active on /templates", () => {
    renderAt("/templates");
    expect(screen.getByRole("link", { name: /Mockup templates/ })).toHaveClass("nav-item--active");
  });
});
