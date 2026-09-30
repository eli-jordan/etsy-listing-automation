import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { useEffect, useId, useRef, useState } from "react";
import { SavedAgo } from "./SavedAgo";

/**
 * The editor head's auto-save chip -- *● Saved 3 mins ago ▾* beside the
 * status -- and the card it opens: the file this editor writes, with Copy,
 * and when it saved (UI doc, *The editor head*).
 *
 * The path is here rather than printed in the head because the head had
 * become a row of competing facts; it matters because this editor writes a
 * file the seller also edits by hand and runs the CLI against, so it is one
 * click away rather than gone.
 */
export function SavedChip({
  path,
  savedAt,
  subject,
}: {
  path: string;
  savedAt: number;
  subject: "listing" | "listing-template";
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const cardId = useId();
  const title = subject === "listing-template" ? "Listing template file" : "Listing file";

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  function copy() {
    // Said only once the clipboard took it: a page without clipboard access
    // (an insecure origin) leaves the path selectable in the card instead.
    void navigator.clipboard
      ?.writeText(path)
      .then(() => setCopied(true))
      .catch(() => undefined);
  }

  return (
    <div className="save-chip" ref={rootRef}>
      <button
        type="button"
        className="save-chip__trigger"
        aria-expanded={open}
        aria-controls={open ? cardId : undefined}
        title="Where this is saved"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="page-head__dot" aria-hidden="true" />
        <SavedAgo savedAt={savedAt} />
        <CaretDownIcon className="save-chip__caret" aria-hidden="true" />
      </button>
      {open && (
        <div className="save-card" id={cardId} role="dialog" aria-label={title}>
          <div className="save-card__title">{title}</div>
          <div className="save-card__path">
            <span className="page-head__path">{path}</span>
            <button type="button" className="save-card__copy" onClick={copy}>
              {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className="save-card__when">
            <SavedAgo savedAt={savedAt} />, automatically
          </div>
        </div>
      )}
    </div>
  );
}
