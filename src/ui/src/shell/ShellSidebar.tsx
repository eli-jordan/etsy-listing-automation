import type { ReactNode } from "react";

/**
 * The app shell's presentational half: design fixtures pass inert navigation
 * without a router or the workspace API. Without `footer` (the app passes its
 * Admin link), the placeholder Setup entry stays.
 */
export function ShellSidebar({
  shopName,
  footer,
  children,
}: {
  shopName: string | null;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
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

      {children}

      {footer !== undefined ? (
        <div className="sidebar__bottom">{footer}</div>
      ) : (
        <div className="sidebar__bottom">
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
      )}
    </aside>
  );
}
