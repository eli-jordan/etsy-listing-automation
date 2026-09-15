/** A minimal stub for this pass (phase-5-listings-ui.md explicitly defers
 * the dashboard's real content) -- the nav item and route exist so the shell
 * is complete, with a body that says what is not built yet rather than
 * showing nothing. */
export function DashboardPage() {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-head__title">Dashboard</h1>
      </div>
      <p className="text-muted">
        Nothing here yet -- see the Listings tab for every draft and published listing.
      </p>
    </div>
  );
}
