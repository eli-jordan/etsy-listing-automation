import { useMenuDismiss } from "../../hooks/useMenuDismiss";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useIsPhone } from "../../phone/usePhone";
import { PhoneSheet } from "../../phone/PhoneSheet";
import { SavedAgo } from "./SavedAgo";

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
  const close = useCallback(() => setOpen(false), []);

  const phone = useIsPhone();
  // A phone shows the card as a bottom sheet on the page body, which closes
  // itself: an outside-press check would read a tap on its Copy as outside.
  useMenuDismiss(open && !phone, rootRef, setOpen);

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

  const card = (
    <>
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
    </>
  );

  return (
    <div className="save-chip" ref={rootRef}>
      <button
        type="button"
        className="save-chip__trigger"
        aria-expanded={open}
        // On a phone the card is a sheet on the page body, which has no id of
        // its own to point at; it says it opens a dialog instead.
        aria-controls={open && !phone ? cardId : undefined}
        {...(phone ? { "aria-haspopup": "dialog" as const } : {})}
        title="Where this is saved"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="page-head__dot" aria-hidden="true" />
        <SavedAgo savedAt={savedAt} />
        <CaretDownIcon className="save-chip__caret" aria-hidden="true" />
      </button>
      {phone && (
        <PhoneSheet open={open} title={title} onClose={close}>
          {card}
        </PhoneSheet>
      )}
      {open && !phone && (
        <div className="save-card" id={cardId} role="dialog" aria-label={title}>
          <div className="save-card__title">{title}</div>
          {card}
        </div>
      )}
    </div>
  );
}
