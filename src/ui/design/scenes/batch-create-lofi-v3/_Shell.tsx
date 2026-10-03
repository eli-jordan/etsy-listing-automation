// Inert copy of the app shell for batch-creation frames. Adds the proposed
// "Listing Templates" nav item; `active` picks the highlighted entry.
import { StackIcon } from "@phosphor-icons/react/dist/csr/Stack";
import type { ReactNode } from "react";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import "./_batch.css";

type NavKey = "dashboard" | "listings" | "listing-templates" | "mockup-templates";

function DashboardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
    </svg>
  );
}

function ListingsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <circle cx="4.5" cy="6" r="1.1" fill="currentColor" stroke="none" />
      <line x1="8.5" y1="6" x2="20" y2="6" />
      <circle cx="4.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <line x1="8.5" y1="12" x2="20" y2="12" />
      <circle cx="4.5" cy="18" r="1.1" fill="currentColor" stroke="none" />
      <line x1="8.5" y1="18" x2="20" y2="18" />
    </svg>
  );
}

function MockupTemplatesIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <rect x="7.5" y="7.5" width="13.5" height="13.5" rx="2" />
      <path d="M3.5 15.5v-10a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

export function Shell({ active, children }: { active: NavKey; children: ReactNode }) {
  const cls = (key: NavKey) => (key === active ? "nav-item nav-item--active" : "nav-item");
  return (
    <div className="shell">
      <ShellSidebar shopName="North & Pine Studio">
        <nav className="sidebar__nav">
          <span className={cls("dashboard")}>
            <DashboardIcon />
            Dashboard
          </span>
          <span className={cls("listings")}>
            <ListingsIcon />
            Listings
          </span>
          <span className={cls("listing-templates")} data-goto="batch-create-lofi-v3/templates">
            <StackIcon />
            Listing Templates
          </span>
          <span className={cls("mockup-templates")}>
            <MockupTemplatesIcon />
            Mockup Templates
          </span>
        </nav>
      </ShellSidebar>
      <main className="shell__main">{children}</main>
    </div>
  );
}
