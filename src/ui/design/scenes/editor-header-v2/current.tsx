import { OpenOnMenu } from "../../../src/components/OpenOnMenu";
import { StatusTag } from "../../../src/components/StatusTag";
import { listing } from "./_fixtures";
import { DeployButton, EditorFrame, SavedState } from "./_parts";

export const meta = {
  title: "Today · the head as shipped · v2",
  viewport: "laptop",
  description:
    "Baseline: Save as listing template floats on its own row above Deploy; the Open on caret, status, path and saved state all share the title row.",
};

export default function Current() {
  return (
    <EditorFrame
      listing={listing}
      head={
        <>
          <div className="bc-row" style={{ marginBottom: "var(--space-2)" }}>
            <span className="bc-spacer" />
            <button type="button" className="btn btn-ghost">
              Save as listing template
            </button>
          </div>
          <div className="page-head page-head--editor">
            <span className="page-head__crumb">Listings</span>
            <span className="page-head__sep">/</span>
            <h1 className="page-head__title">{listing.name}</h1>
            <OpenOnMenu
              etsyListingId={listing.etsyListingId}
              printifyProductId={listing.printifyProductId}
            />
            <StatusTag status={listing.status} />
            <span className="page-head__meta">
              <span className="page-head__path">{listing.path}</span>
              {" · "}
              <SavedState listing={listing} />
            </span>
            <div className="page-head__actions">
              <DeployButton />
            </div>
          </div>
        </>
      }
    />
  );
}
