import type { ReactNode } from "react";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";

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

function TemplatesIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
      <rect x="7.5" y="7.5" width="13.5" height="13.5" rx="2" />
      <path d="M3.5 15.5v-10a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

export default function BatchDeployLayout({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <ShellSidebar shopName="North & Pine Studio">
        <nav className="sidebar__nav">
          <span className="nav-item">
            <DashboardIcon />
            Dashboard
          </span>
          <span className="nav-item nav-item--active">
            <ListingsIcon />
            Listings
          </span>
          <span className="nav-item">
            <TemplatesIcon />
            Mockup Templates
          </span>
        </nav>
      </ShellSidebar>
      <main className="shell__main">{children}</main>
    </div>
  );
}
