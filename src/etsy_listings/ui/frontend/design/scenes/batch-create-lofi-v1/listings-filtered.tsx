import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { StatusTag } from "../../../src/components/StatusTag";
import { Shell } from "./_Shell";
import { batchLabel, batchRows } from "./_fixtures";

export const meta = {
  title: "Listings — filtered to a batch · v1",
  viewport: "laptop",
  description:
    "Wireframe: the ordinary Listings table narrowed to one batch, with a review column and a way back to the summary.",
};

export default function ListingsFilteredToBatch() {
  const rows = batchRows.filter((r) => r.ai !== "not-created" && r.ai !== "deleted");
  return (
    <Shell active="listings">
      <div className="page-head">
        <h1 className="page-head__title">Listings</h1>
        <span className="page-head__meta">{rows.length} shown of 38</span>
        <div className="page-head__actions">
          <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi-v1/new-batch">
            New batch
          </button>
          <button type="button" className="btn btn-primary">
            + New listing
          </button>
        </div>
      </div>

      <div className="toolbar">
        <input className="input toolbar__search" type="text" placeholder="Search listings…" aria-label="Search listings" />
        <label className="toolbar__filter">
          <span className="toolbar__filter-label">Status</span>
          <select className="input" defaultValue="all">
            <option value="all">All statuses</option>
          </select>
        </label>
        <label className="toolbar__filter">
          <span className="toolbar__filter-label">Batch</span>
          <span className="bc-filter-chip">
            {batchLabel}
            <button type="button" className="bc-filter-chip__x" aria-label="Clear batch filter">
              <XIcon size={16} />
            </button>
          </span>
        </label>
        <span className="bc-spacer" />
        <button type="button" className="bc-link bc-small" data-goto="batch-create-lofi-v1/batch-summary">
          Open batch summary
        </button>
      </div>

      <table className="listings">
        <thead>
          <tr>
            <th>Listing</th>
            <th>Garment</th>
            <th>Status</th>
            <th>Batch review</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              <td>
                <div className="listing-cell">
                  <span className="listing-thumb listing-thumb--empty" />
                  <button type="button" className="listing-row__link">
                    {row.name}
                  </button>
                </div>
              </td>
              <td className="listing-row__garment">Comfort Colors 1717</td>
              <td>
                <span className="listings__status">
                  <StatusTag status="draft" />
                </span>
              </td>
              <td className="bc-small">
                {row.reviewed
                  ? "Reviewed"
                  : row.proposal === "ready"
                    ? "SEO proposal ready"
                    : row.proposal === "stale"
                      ? "Proposal stale"
                      : row.ai === "failed"
                        ? "AI failed, retry from summary"
                        : row.ai === "drafting"
                          ? "Drafting…"
                          : "Queued"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  );
}
