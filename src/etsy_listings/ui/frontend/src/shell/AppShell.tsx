import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getWorkspace } from "../api/listings";
import { ShellSidebar } from "./ShellSidebar";

/**
 * The app shell (phase 5): a fixed sidebar (brand, nav, a placeholder Setup
 * entry) around whatever page the router picks, from the design mockup's
 * app-shell markup (`Main.dc.html`). The Dashboard/Listings/Mockup Templates
 * routes are declared by the caller (`main.tsx`) as child routes rendered
 * into `<Outlet/>` -- this component only ever draws the chrome around them.
 */

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? "nav-item nav-item--active" : "nav-item";
}

export function AppShell() {
  // One workspace is one shop, and the sidebar is where that is said. A
  // failure is silence, not an error banner: the shop's name is orientation,
  // and no page here stops working without it.
  const [shopName, setShopName] = useState<string | null>(null);

  useEffect(() => {
    getWorkspace()
      .then((workspace) => setShopName(workspace.shop_name))
      .catch(() => setShopName(null));
  }, []);

  return (
    <div className="shell">
      <ShellSidebar shopName={shopName}>
        <nav className="sidebar__nav">
          <NavLink to="/" end className={navClass}>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
              <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
              <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
              <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
            </svg>
            Dashboard
          </NavLink>
          <NavLink to="/listings" className={navClass}>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="4.5" cy="6" r="1.1" fill="currentColor" stroke="none" />
              <line x1="8.5" y1="6" x2="20" y2="6" />
              <circle cx="4.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
              <line x1="8.5" y1="12" x2="20" y2="12" />
              <circle cx="4.5" cy="18" r="1.1" fill="currentColor" stroke="none" />
              <line x1="8.5" y1="18" x2="20" y2="18" />
            </svg>
            Listings
          </NavLink>
          <NavLink to="/templates" className={navClass}>
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="7.5" y="7.5" width="13.5" height="13.5" rx="2" />
              <path d="M3.5 15.5v-10a2 2 0 0 1 2-2h10" />
            </svg>
            Mockup Templates
          </NavLink>
        </nav>
      </ShellSidebar>

      <main className="shell__main">
        <Outlet />
      </main>
    </div>
  );
}
