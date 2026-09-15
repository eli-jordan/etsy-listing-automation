import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getWorkspace } from "../api/listings";

/**
 * The app shell (phase 5): a fixed sidebar (brand, nav, a placeholder Setup
 * entry) around whatever page the router picks, from the design mockup's
 * app-shell markup (`Main.dc.html`). The Dashboard/Listings/Mockup templates
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
      <aside className="sidebar">
        <div className="sidebar__brand">
          <div className="sidebar__mark">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--color-bg)"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M8 3 L6 6 L4 8 L5 11 L8 10 L8 20 L16 20 L16 10 L19 11 L20 8 L18 6 L16 3 Q14 5 12 5 Q10 5 8 3 Z" />
            </svg>
          </div>
          <div>
            <div className="sidebar__wordmark">Listings</div>
            {shopName !== null && (
              <div className="sidebar__shop">
                <span className="sidebar__dot" aria-hidden="true" />
                {shopName}
              </div>
            )}
          </div>
        </div>

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
            Mockup templates
          </NavLink>
        </nav>

        <div className="sidebar__bottom">
          {/* Not a route yet -- `auth`/`setup` stay CLI-only until a later
              pass wires the setup wizard into this shell. */}
          <div className="nav-item nav-item--secondary">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="4" y1="6" x2="20" y2="6" />
              <circle cx="9" cy="6" r="2" fill="var(--color-surface)" />
              <line x1="4" y1="12" x2="20" y2="12" />
              <circle cx="15" cy="12" r="2" fill="var(--color-surface)" />
              <line x1="4" y1="18" x2="20" y2="18" />
              <circle cx="11" cy="18" r="2" fill="var(--color-surface)" />
            </svg>
            Setup
          </div>
        </div>
      </aside>

      <main className="shell__main">
        <Outlet />
      </main>
    </div>
  );
}
