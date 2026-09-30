import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { FileIcon } from "@phosphor-icons/react/dist/csr/File";
import { StackIcon } from "@phosphor-icons/react/dist/csr/Stack";
import { useEffect, useState } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { listing } from "./_fixtures";
import { DeployButton, EditorBody, SavedState } from "./_parts";

export const meta = {
  title: "E · Status bar · v1",
  viewport: "laptop",
  description:
    "Retired in round 2 (C won, taking D's file card): Head is only crumb, name, status and Deploy; an editor status bar pinned to the bottom holds the file path + Copy, saved state, Open on links and Save as listing template.",
};

export default function StatusBar() {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied]);

  return (
    <div className="hdr-e-page">
      <div className="editor">
        <div className="page-head page-head--editor hdr-head">
          <span className="page-head__crumb">Listings</span>
          <span className="page-head__sep">/</span>
          <h1 className="page-head__title">{listing.name}</h1>
          <StatusTag status={listing.status} />
          <div className="page-head__actions">
            <DeployButton />
          </div>
        </div>
        <EditorBody listing={listing} />
      </div>
      <footer className="hdr-statusbar" aria-label="Listing file">
        <FileIcon />
        <span className="hdr-path">{listing.path}</span>
        <button type="button" className="hdr-copy" onClick={() => setCopied(true)}>
          {copied ? <CheckIcon /> : <CopyIcon />}
          {copied ? "Copied" : "Copy"}
        </button>
        <SavedState listing={listing} />
        <span className="hdr-statusbar__end">
          <a className="hdr-link" href="#etsy" target="_blank" rel="noreferrer">
            Open on Etsy <ArrowSquareOutIcon />
          </a>
          <a className="hdr-link" href="#printify" target="_blank" rel="noreferrer">
            Open on Printify <ArrowSquareOutIcon />
          </a>
          <button type="button" className="hdr-link">
            <StackIcon /> Save as listing template
          </button>
        </span>
      </footer>
    </div>
  );
}
