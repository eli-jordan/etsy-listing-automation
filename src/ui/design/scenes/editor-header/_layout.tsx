// The real app shell around every editor-header frame: sidebar + main column,
// so each direction is judged where it will live, not floating on a blank page.
import type { ReactNode } from "react";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import "./_header.css";

function NavIcon({ d }: { d: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      {d}
    </svg>
  );
}

export default function EditorHeaderLayout({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <ShellSidebar shopName="NaturallyInkedStudio">
        <nav className="sidebar__nav" aria-label="App navigation">
          <a className="nav-item" href="#dashboard">
            <NavIcon d={<><rect x="3" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" /></>} />
            Dashboard
          </a>
          <a className="nav-item nav-item--active" href="#listings">
            <NavIcon d={<><line x1="8.5" y1="6" x2="20" y2="6" /><line x1="8.5" y1="12" x2="20" y2="12" /><line x1="8.5" y1="18" x2="20" y2="18" /><circle cx="4.5" cy="6" r="1.1" fill="currentColor" stroke="none" /><circle cx="4.5" cy="12" r="1.1" fill="currentColor" stroke="none" /><circle cx="4.5" cy="18" r="1.1" fill="currentColor" stroke="none" /></>} />
            Listings
          </a>
          <a className="nav-item" href="#listing-templates">
            <NavIcon d={<><path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" /></>} />
            Listing Templates
          </a>
          <a className="nav-item" href="#templates">
            <NavIcon d={<><rect x="7.5" y="7.5" width="13.5" height="13.5" rx="2" /><path d="M3.5 15.5v-10a2 2 0 0 1 2-2h10" /></>} />
            Mockup Templates
          </a>
        </nav>
      </ShellSidebar>
      <main className="shell__main">{children}</main>
    </div>
  );
}
