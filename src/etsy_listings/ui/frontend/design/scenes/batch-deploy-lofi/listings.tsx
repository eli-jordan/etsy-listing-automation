import { StatusTag } from "../../../src/components/StatusTag";
import type { ListingStatus } from "../../../src/types";

export const meta = {
  title: "Listings — batch deploy entry",
  viewport: "laptop",
  description:
    "Hi-fi fixture of the real Listings page with the batch deploy entry and its hover summary.",
};

const rows: {
  name: string;
  garment: string;
  status: ListingStatus;
  colours: number;
  action: string;
}[] = [
  {
    name: "Mountain sunrise tee",
    garment: "Comfort Colors 1717",
    status: "dirty",
    colours: 5,
    action: "Mark for deletion",
  },
  {
    name: "Night hike club",
    garment: "Bella + Canvas 3001",
    status: "draft",
    colours: 4,
    action: "Delete",
  },
  {
    name: "After rain trail",
    garment: "Comfort Colors 1717",
    status: "draft",
    colours: 3,
    action: "Delete",
  },
  {
    name: "Cedar trail shirt",
    garment: "Comfort Colors 1717",
    status: "dirty",
    colours: 5,
    action: "Mark for deletion",
  },
  {
    name: "Fjord mornings",
    garment: "Bella + Canvas 3001",
    status: "dirty",
    colours: 2,
    action: "Mark for deletion",
  },
  {
    name: "Old logo tee",
    garment: "Gildan 5000",
    status: "pending-delete",
    colours: 1,
    action: "",
  },
  {
    name: "Moss and miles",
    garment: "Comfort Colors 1717",
    status: "live",
    colours: 4,
    action: "Retire",
  },
  {
    name: "Slow Sunday club",
    garment: "Bella + Canvas 3001",
    status: "deployed",
    colours: 3,
    action: "Retire",
  },
];

export default function ListingsAppPrototype() {
  return (
    <div>
      <style>{`
        .batch-deploy { position:relative; }
        .batch-deploy__button { display:inline-flex; gap:8px; white-space:nowrap; }
        .batch-deploy__button > svg { width:15px; height:15px; }
        .batch-deploy__counts { display:inline-flex; gap:3px; padding-left:8px; border-left:1px solid color-mix(in srgb,var(--color-bg) 38%,transparent); font-family:var(--font-body); }
        .batch-deploy__counts .tag { min-width:23px; justify-content:center; padding:1px 5px; font-size:10px; line-height:1.3; font-weight:700; font-variant-numeric:tabular-nums; }
        .batch-deploy__popup { position:absolute; top:calc(100% + 8px); right:0; z-index:30; width:320px; padding:var(--space-3); border:1px solid var(--color-divider); border-radius:var(--radius-sm); background:var(--color-neutral-100); box-shadow:var(--shadow-md); opacity:0; visibility:hidden; transform:translateY(-4px); transition:opacity .12s ease,transform .12s ease; pointer-events:none; }
        .batch-deploy:hover .batch-deploy__popup,.batch-deploy:focus-within .batch-deploy__popup { opacity:1; visibility:visible; transform:translateY(0); }
        .batch-deploy__popup h3 { font:700 13px/1.3 var(--font-body); margin:0 0 var(--space-2); }
        .batch-deploy__group { display:grid; grid-template-columns:auto 1fr; gap:2px 9px; padding:var(--space-2) 0; border-top:1px solid var(--color-divider); }
        .batch-deploy__group:first-of-type { border-top:0; }
        .batch-deploy__group strong { font-size:12px; }
        .batch-deploy__group span:last-child { grid-column:2; font-size:11.5px; color:color-mix(in srgb,var(--color-text) 58%,transparent); }
        .batch-deploy__note { margin:var(--space-2) 0 0; padding-top:var(--space-2); border-top:1px solid var(--color-divider); font-size:11px; color:color-mix(in srgb,var(--color-text) 55%,transparent); }
        @media(max-width:800px){.page-head__actions{width:100%;margin-left:0}.toolbar__search{width:100%}.listings__optional{display:none}.batch-deploy__popup{right:auto;left:0}}
      `}</style>

      <div className="page-head">
        <h1 className="page-head__title">Listings</h1>
        <span className="page-head__meta">8 shown</span>
        <div className="page-head__actions">
          <button type="button" className="btn btn-primary">
            + New listing
          </button>
          <div className="batch-deploy">
            <button
              type="button"
              className="btn btn-primary batch-deploy__button"
              data-goto="batch-deploy-lofi/review-bottom-sheet"
            >
              <span>Deploy changes</span>
              <span className="batch-deploy__counts" aria-label="2 to add, 1 to remove, 3 to edit">
                <span className="tag tag-accent-2">+2</span>
                <span className="tag tag-dirty">−1</span>
                <span className="tag tag-accent">~3</span>
              </span>
              <svg
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M4 10h12M11 5l5 5-5 5" />
              </svg>
            </button>
            <aside className="batch-deploy__popup">
              <h3>6 pending listing changes</h3>
              <div className="batch-deploy__group">
                <span className="tag tag-accent-2">+2</span>
                <strong>Add</strong>
                <span>Night hike club · After rain trail</span>
              </div>
              <div className="batch-deploy__group">
                <span className="tag tag-accent">~3</span>
                <strong>Edit</strong>
                <span>Mountain sunrise · Cedar trail · Fjord mornings</span>
              </div>
              <div className="batch-deploy__group">
                <span className="tag tag-dirty">−1</span>
                <strong>Remove</strong>
                <span>Old logo tee</span>
              </div>
              <p className="batch-deploy__note">
                Open to generate a fresh plan across all listings.
              </p>
            </aside>
          </div>
        </div>
      </div>

      <div className="toolbar">
        <input
          className="input toolbar__search"
          type="text"
          placeholder="Search listings…"
          aria-label="Search listings"
        />
        <label className="toolbar__filter">
          <span className="toolbar__filter-label">Status</span>
          <select className="input" defaultValue="all">
            <option value="all">All statuses</option>
            <option>Draft</option>
            <option>Live</option>
            <option>Dirty</option>
          </select>
        </label>
      </div>

      <table className="listings">
        <thead>
          <tr>
            <th>Listing</th>
            <th className="listings__optional">Garment</th>
            <th>Status</th>
            <th className="listings__actions"> </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              <td>
                <div className="listing-cell">
                  <span className="listing-hover">
                    <span className="listing-thumb listing-thumb--empty" />
                    <button type="button" className="listing-row__link">
                      {row.name}
                    </button>
                    <span className="listing-popup">
                      <span className="listing-popup__thumb listing-thumb--empty" />
                      <span className="listing-popup__name">{row.name}</span>
                      <span className="listing-popup__garment">{row.garment}</span>
                      <span className="listing-popup__meta">
                        <StatusTag status={row.status} />
                        <span>{row.colours} colours</span>
                      </span>
                    </span>
                  </span>
                </div>
              </td>
              <td className="listing-row__garment listings__optional">{row.garment}</td>
              <td>
                <span className="listings__status">
                  <StatusTag status={row.status} />
                </span>
              </td>
              <td className="listings__actions">
                {row.action && (
                  <button
                    type="button"
                    className={
                      row.action.includes("deletion") ? "listings__quiet" : "btn btn-ghost"
                    }
                  >
                    {row.action}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
