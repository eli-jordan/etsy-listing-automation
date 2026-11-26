import { GearIcon } from "@phosphor-icons/react/dist/csr/Gear";
import { StackIcon } from "@phosphor-icons/react/dist/csr/Stack";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { getWorkspace } from "../api/listings";
import "../pages/admin/backup/backup.css";
import { useIsPhone } from "../phone/usePhone";
import { useBackupStatus } from "./backupStatus";
import { BackupStatusProvider } from "./BackupStatusProvider";
import { pageTitle } from "./pageTitle";
import { ShellSidebar } from "./ShellSidebar";

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? "nav-item nav-item--active" : "nav-item";
}

/** A phone's tab bar gives each entry a fifth of the width. */
function navLabel(isPhone: boolean, full: string, short: string) {
  return isPhone ? { label: short, aria: full } : { label: full, aria: undefined };
}

export function AppShell() {
  return (
    <BackupStatusProvider>
      <Shell />
    </BackupStatusProvider>
  );
}

function Shell() {
  const [shopName, setShopName] = useState<string | null>(null);
  const { pathname } = useLocation();
  const underListingTemplates = pathname.startsWith("/batches/");
  const warning = useBackupStatus().view.banner;
  const isPhone = useIsPhone();
  const listingTemplates = navLabel(isPhone, "Listing Templates", "Templates");
  const mockupTemplates = navLabel(isPhone, "Mockup Templates", "Mockups");

  useEffect(() => {
    document.title = pageTitle(pathname);
  }, [pathname]);

  useEffect(() => {
    getWorkspace()
      .then((workspace) => setShopName(workspace.shop_name))
      .catch(() => setShopName(null));
  }, []);

  return (
    <div className="shell">
      <ShellSidebar
        shopName={shopName}
        footer={
          <NavLink to="/admin" className={navClass}>
            <GearIcon size={18} />
            Admin
            {warning && (
              <span className="bk-nav-dot" role="img" aria-label="Backups need attention" />
            )}
          </NavLink>
        }
      >
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
          <NavLink
            to="/listing-templates"
            className={({ isActive }) => navClass({ isActive: isActive || underListingTemplates })}
            aria-label={listingTemplates.aria}
          >
            <StackIcon />
            {listingTemplates.label}
          </NavLink>
          <NavLink to="/templates" className={navClass} aria-label={mockupTemplates.aria}>
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
            {mockupTemplates.label}
          </NavLink>
        </nav>
      </ShellSidebar>

      <main className="shell__main">
        {warning && !pathname.startsWith("/admin") && (
          <div className="adm-warn bk-global" role="alert">
            <WarningIcon size={18} weight="fill" />
            <span>
              <strong>Backups need attention.</strong> {warning.message}
            </span>
            <Link to="/admin?section=backup" className="btn btn-secondary bk-banner__btn">
              Open Backup
            </Link>
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
