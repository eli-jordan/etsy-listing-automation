import { ArrowClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowClockwise";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { ClockIcon } from "@phosphor-icons/react/dist/csr/Clock";
import { MinusCircleIcon } from "@phosphor-icons/react/dist/csr/MinusCircle";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { EditableName } from "../../../src/components/EditableName";
import { AiWorkflowIndicator } from "../../../src/pages/editor/aiSeo/AiWorkflowIndicator";
import type { WorkflowStep } from "../../../src/types";
import { Shell } from "./_Shell";
import { artFor, batchLabel, batchRows, type BatchRowFixture } from "./_fixtures";

/** The editor's own brief → market → SEO steps, as each row's run left them. */
function steps(brief: WorkflowStep["state"], market: WorkflowStep["state"], seo: WorkflowStep["state"]): WorkflowStep[] {
  return [
    { id: "brief", state: brief },
    { id: "market", state: market },
    { id: "seo", state: seo },
  ];
}

export const meta = {
  title: "Batch summary",
  viewport: "laptop",
  description:
    "The batch's one review surface mid-queue, with the editor's own AI step indicator on running and failed rows.",
};

const ORDINAL = ["", "next", "2nd", "3rd"];

function AiCell({ row }: { row: BatchRowFixture }) {
  switch (row.ai) {
    case "drafted":
      return (
        <span className="bc-status bc-status--ok">
          <CheckCircleIcon className="bc-icon" />
          Brief, market research and SEO done
        </span>
      );
    case "drafting":
      return <AiWorkflowIndicator steps={steps("done", "active", "pending")} running />;
    case "queued":
      return (
        <span className="bc-status bc-status--info">
          <ClockIcon className="bc-icon" />
          Queued, {ORDINAL[row.queue ?? 0]} in line
        </span>
      );
    case "failed":
      return (
        <span className="bc-cell__text bc-aiflow-cell" style={{ gap: 4 }}>
          <AiWorkflowIndicator steps={steps("done", "failed", "pending")} running={false} />
          <span className="bc-status bc-status--error">
            <span className="bc-status__text">{row.error}</span>
          </span>
        </span>
      );
    case "not-created":
      return (
        <span className="bc-status bc-status--error">
          <WarningCircleIcon className="bc-icon" />
          <span className="bc-status__text">{row.error}</span>
        </span>
      );
    case "deleted":
      return (
        <span className="bc-status bc-status--info">
          <MinusCircleIcon className="bc-icon" />
          Listing deleted. Its AI work was cancelled.
        </span>
      );
  }
}

function ProposalCell({ row }: { row: BatchRowFixture }) {
  if (row.proposal === "ready") return <span className="tag tag-accent">Ready to review</span>;
  if (row.proposal === "stale")
    return (
      <span className="bc-status bc-status--warn">
        <WarningIcon className="bc-icon" />
        <span className="bc-status__text">Stale: brief edited since</span>
      </span>
    );
  return <span className="bc-muted">—</span>;
}

export default function BatchSummary() {
  const created = batchRows.filter((r) => r.ai !== "not-created" && r.ai !== "deleted");
  const reviewed = batchRows.filter((r) => r.reviewed).length;
  const total = batchRows.length;
  const count = (states: BatchRowFixture["ai"][]) => batchRows.filter((r) => states.includes(r.ai)).length;
  const segments: [number, string][] = [
    [count(["drafted"]), "var(--color-accent-2)"],
    [count(["drafting"]), "var(--color-accent)"],
    [count(["queued"]), "var(--color-neutral-500)"],
    [count(["failed", "not-created"]), "var(--color-danger)"],
  ];

  return (
    <Shell active="listing-templates">
      <div className="page-head">
        <span className="page-head__crumb" data-goto="batch-create-lofi/templates">
          Listing templates
        </span>
        <span className="page-head__sep">/</span>
        <EditableName value={batchLabel} onCommit={() => {}} label="Batch label" placeholder="Name this batch…" />
        <span className="page-head__meta">Double-click the label to rename it</span>
        <div className="page-head__actions">
          <button type="button" className="btn btn-secondary">
            Cancel batch
          </button>
        </div>
      </div>

      <div className="bc-progress" aria-hidden="true">
        {segments.map(([n, color]) => (
          <span key={color} style={{ width: `${(n / total) * 100}%`, background: color }} />
        ))}
      </div>

      <div className="bc-counts">
        <span className="bc-count">
          <span className="bc-dot bc-dot--ok" />
          <strong>{count(["drafted"])}</strong> drafted
        </span>
        <span className="bc-count">
          <span className="bc-dot bc-dot--busy" />
          <strong>{count(["drafting"])}</strong> drafting
        </span>
        <span className="bc-count">
          <span className="bc-dot" />
          <strong>{count(["queued"])}</strong> queued
        </span>
        <span className="bc-count">
          <span className="bc-dot bc-dot--error" />
          <strong>{count(["failed", "not-created"])}</strong> need retry
        </span>
        <span className="bc-count bc-muted">
          <strong>{count(["deleted"])}</strong> deleted
        </span>
        <span className="bc-spacer" />
        <span className="bc-count">
          <strong>
            {reviewed} of {created.length}
          </strong>{" "}
          reviewed
        </span>
        <button type="button" className="btn btn-secondary">
          <ArrowClockwiseIcon className="bc-icon" style={{ verticalAlign: -3, marginRight: 6 }} />
          Retry 2 failed
        </button>
      </div>

      <p className="bc-small bc-muted" style={{ margin: "0 0 var(--space-3)" }}>
        Created today at 11:42 from heavyweight-tee. Drafting one listing at a time. Work carries on if you close this tab. Briefs are written for
        you; titles, tags and the description lead wait for you to accept them in each listing.
      </p>

      <table className="listings bc-table">
        <thead>
          <tr>
            <th style={{ width: "22%" }}>Listing</th>
            <th>AI drafting</th>
            <th style={{ width: "17%" }}>SEO proposal</th>
            <th style={{ width: "14%" }}>Reviewed</th>
            <th className="bc-end"> </th>
          </tr>
        </thead>
        <tbody>
          {batchRows.map((row, i) => {
            const gone = row.ai === "deleted" || row.ai === "not-created";
            return (
              <tr key={row.name} className={gone ? "bc-tr--muted" : undefined}>
                <td>
                  <span className="bc-cell">
                    <img className="listing-thumb" src={artFor(row.name, i)} alt="" />
                    {gone ? (
                      <span className={row.ai === "deleted" ? "bc-muted" : undefined} style={{ fontWeight: 600 }}>
                        {row.ai === "deleted" ? <s>{row.name}</s> : row.name}
                      </span>
                    ) : (
                      <button type="button" className="listing-row__link" data-goto="batch-create-lofi/listing-from-batch">
                        {row.name}
                      </button>
                    )}
                  </span>
                </td>
                <td>
                  <AiCell row={row} />
                </td>
                <td>
                  <ProposalCell row={row} />
                </td>
                <td>
                  {gone || row.ai === "queued" || row.ai === "drafting" ? (
                    <span className="bc-muted">—</span>
                  ) : row.reviewed ? (
                    <button type="button" className="bc-quiet bc-quiet--on" title="Mark needs review">
                      <CheckIcon className="bc-icon" style={{ width: 12, height: 12, verticalAlign: -2, marginRight: 4 }} />
                      Reviewed
                    </button>
                  ) : (
                    <button type="button" className="bc-quiet">
                      Mark reviewed
                    </button>
                  )}
                </td>
                <td className="bc-end">
                  {(row.ai === "failed" || row.ai === "not-created") && (
                    <button type="button" className="btn btn-ghost">
                      Retry
                    </button>
                  )}
                  {!gone && (
                    <button type="button" className="btn btn-ghost" data-goto="batch-create-lofi/listing-from-batch">
                      Open
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="bc-row" style={{ marginTop: "var(--space-4)" }}>
        <span className="bc-small bc-muted">
          Deleting the batch record keeps every listing, design and brief it created.
        </span>
        <button type="button" className="bc-quiet">
          <TrashIcon className="bc-icon" style={{ width: 12, height: 12, verticalAlign: -2, marginRight: 4 }} />
          Delete batch record
        </button>
      </div>
    </Shell>
  );
}
