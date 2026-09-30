import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { StackIcon } from "@phosphor-icons/react/dist/csr/Stack";
import { useEffect, useState } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { listing } from "./_fixtures";
import { DeployButton, EditorFrame, SavedState } from "./_parts";

export const meta = {
  title: "C · Identity row + action row · v1",
  viewport: "laptop",
  description:
    "Round 1 pick - refined into the live header (Open in dropdown, file card, delete): Two rows: name, status and Deploy on top; a quiet link row underneath carries Open on Etsy/Printify, Save as listing template, Copy path and the saved state. Nothing hidden.",
};

export default function ActionRow() {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied]);

  return (
    <EditorFrame
      listing={listing}
      head={
        <>
          <div className="page-head page-head--editor hdr-head hdr-c-head">
            <span className="page-head__crumb">Listings</span>
            <span className="page-head__sep">/</span>
            <h1 className="page-head__title">{listing.name}</h1>
            <StatusTag status={listing.status} />
            <div className="page-head__actions">
              <DeployButton />
            </div>
          </div>
          <div className="hdr-subrow">
            <a className="hdr-link" href="#etsy" target="_blank" rel="noreferrer">
              Open on Etsy <ArrowSquareOutIcon />
            </a>
            <a className="hdr-link" href="#printify" target="_blank" rel="noreferrer">
              Open on Printify <ArrowSquareOutIcon />
            </a>
            <span className="hdr-subrow__sep" aria-hidden="true" />
            <button type="button" className="hdr-link">
              <StackIcon /> Save as listing template
            </button>
            <span className="hdr-subrow__end">
              <button
                type="button"
                className="hdr-link"
                title={listing.path}
                onClick={() => setCopied(true)}
              >
                {copied ? <CheckIcon /> : <CopyIcon />}
                {copied ? "Copied" : "Copy path"}
              </button>
              <span className="hdr-subrow__sep" aria-hidden="true" />
              <SavedState listing={listing} />
            </span>
          </div>
        </>
      }
    />
  );
}
