// A batch-created listing opened from the batch summary, in the real
// ListingEditorShell (IssuesBanner, DesignSelect, tab bar, real DetailsTab
// with AI Mode). The head copies EditorHead's markup and adds the three
// batch pieces: Back to batch, Mark reviewed and Save as listing template.
//
// The out-of-date title drawer is the real AiChoiceDrawer: since batch PR 3
// it keeps a stale proposal's choices usable and names what changed in its
// heading, which this frame used to patch in on mount.
import "./_mockApi";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { useEffect, useRef } from "react";
import { EditableName } from "../../../src/components/EditableName";
import { StatusTag } from "../../../src/components/StatusTag";
import { ListingEditorShell } from "../../../src/pages/ListingEditorPage";
import { metaFor } from "../../../src/pages/editor/saveMeta";
import { Shell } from "./_Shell";
import { batchListing, staleAiSeo } from "./_editorFixtures";
import { batchLabel } from "./_fixtures";

const noop = () => {};

export function ListingFromBatch() {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = root.current;
    if (el === null) return;
    // Open on Listing Details, where the batch's review work is.
    const details = Array.from(el.querySelectorAll<HTMLElement>(".tabs .seg-opt")).find(
      (t) => t.textContent?.startsWith("Listing Details"),
    );
    details?.click();
  }, []);

  const head = (
    <div className="page-head page-head--editor">
      <span className="page-head__crumb">Listings</span>
      <span className="page-head__sep">/</span>
      <EditableName value={batchListing.name} onCommit={noop} />
      <StatusTag status={batchListing.status} />
      <span className="page-head__meta">
        {metaFor({ kind: "saved", savedAt: Date.now() }, batchListing.name)}
      </span>
      <div className="page-head__actions dv-head-actions">
        <button type="button" className="btn btn-primary">
          Deploy changes &rarr;
        </button>
      </div>
    </div>
  );

  return (
    <Shell active="listings">
      <div ref={root}>
        <div className="bc-row" style={{ marginBottom: "var(--space-2)" }}>
          <button type="button" className="btn btn-secondary bc-back" data-goto="batch-create-lofi/batch-summary">
            <ArrowLeftIcon />
            Back to batch {batchLabel}
          </button>
          <span className="bc-spacer" />
          <button type="button" className="btn btn-ghost" data-goto="batch-create-lofi/template-new">
            Save as listing template
          </button>
          <button type="button" className="btn btn-secondary" aria-pressed="false">
            <CheckIcon style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 6 }} />
            Mark reviewed
          </button>
        </div>
        <ListingEditorShell
          detail={batchListing}
          update={noop}
          flush={noop}
          onPickDesign={noop}
          aiSeo={staleAiSeo}
          head={head}
        />
      </div>
    </Shell>
  );
}
