// Shared pieces for the editor-header directions: the part of the editor
// below the head (identical in every direction, so only the head differs),
// a menu built on the app's own row-menu styles, and the Deploy button.
import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { StackIcon } from "@phosphor-icons/react/dist/csr/Stack";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { IssuesBanner } from "../../../src/pages/editor/IssuesBanner";
import type { HeaderListing } from "./_fixtures";
import dukeArt from "../../assets/editor-header/duke-java-developer.svg";

export function DeployButton() {
  return (
    <button type="button" className="btn btn-primary">
      Deploy changes &rarr;
    </button>
  );
}

export function SavedState({ listing }: { listing: HeaderListing }) {
  return (
    <span className="page-head__saved">
      <span className="page-head__dot" aria-hidden="true" />
      {listing.savedAgo}
    </span>
  );
}

/** Closes on an outside press and on Escape, like the app's OpenOnMenu. */
export function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function onDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) close();
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

export function MenuPanel({
  children,
  align = "right",
  style,
  label,
}: {
  children: ReactNode;
  align?: "left" | "right";
  style?: React.CSSProperties;
  label: string;
}) {
  return (
    <div
      className={`row-menu__panel hdr-menu hdr-menu--${align}`}
      role="menu"
      aria-label={label}
      style={style}
    >
      {children}
    </div>
  );
}

export function MenuDivider() {
  return <div className="hdr-menu__divider" role="separator" />;
}

export function MenuItem({
  icon,
  children,
  hint,
  href,
  onSelect,
}: {
  icon: ReactNode;
  children: ReactNode;
  hint?: ReactNode;
  href?: string;
  onSelect?: () => void;
}) {
  const body = (
    <>
      <span className="hdr-menu__icon">{icon}</span>
      <span className="hdr-menu__text">
        <span className="hdr-menu__label">{children}</span>
        {hint && <span className="hdr-menu__hint">{hint}</span>}
      </span>
    </>
  );
  return href ? (
    <a className="row-menu__item" role="menuitem" href={href} target="_blank" rel="noreferrer">
      {body}
    </a>
  ) : (
    <button type="button" className="row-menu__item" role="menuitem" onClick={onSelect}>
      {body}
    </button>
  );
}

/** "Copy listing path", which says "Copied" for a moment after the click. */
export function CopyPathItem({ listing }: { listing: HeaderListing }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <MenuItem
      icon={copied ? <CheckIcon /> : <CopyIcon />}
      hint={<span className="hdr-path">{listing.path}</span>}
      onSelect={() => setCopied(true)}
    >
      {copied ? "Copied listing path" : "Copy listing path"}
    </MenuItem>
  );
}

export function OpenOnItems({ listing }: { listing: HeaderListing }) {
  return (
    <>
      {listing.etsyListingId !== null && (
        <MenuItem
          icon={<span className="row-menu__badge row-menu__badge--etsy">E</span>}
          href="#etsy"
        >
          Open on Etsy <ArrowSquareOutIcon className="hdr-menu__ext" />
        </MenuItem>
      )}
      {listing.printifyProductId !== null && (
        <MenuItem
          icon={<span className="row-menu__badge row-menu__badge--printify">P</span>}
          href="#printify"
        >
          Open on Printify <ArrowSquareOutIcon className="hdr-menu__ext" />
        </MenuItem>
      )}
    </>
  );
}

export function SaveAsTemplateItem() {
  return (
    <MenuItem icon={<StackIcon />} hint="Start a listing template from this listing">
      Save as listing template
    </MenuItem>
  );
}

/** Everything below the head, the same in every direction. */
export function EditorBody({ listing }: { listing: HeaderListing }) {
  return (
    <>
      <IssuesBanner issues={listing.issues} activeTab="variants" onJumpTo={() => {}} />
      <div className="design-select">
        <div className="design-row">
          <img className="design-thumb" src={dukeArt} alt="" />
          <div className="design-row__text">
            <div className="design-row__name">{listing.design.name}</div>
            <div className="design-row__file">{listing.design.file}</div>
          </div>
          <button type="button" className="design-row__change">
            Change ▾
          </button>
        </div>
      </div>
      <div className="tabs seg">
        <div className="seg-opt">Variants</div>
        <div className="seg-opt">Pricing</div>
        <div className="seg-opt">Listing Images</div>
        <div className="seg-opt seg-opt--on">
          Listing Details <span className="tab-badge tab-badge--warn">1</span>
        </div>
      </div>
      <div className="details-tab hdr-details">
        <div className="field">
          <label>Title</label>
          <input type="text" className="input" defaultValue="Duke Java Developer" />
        </div>
        <div className="field">
          <label>Description lead</label>
          <textarea className="input" rows={2} placeholder="The opening paragraph a shopper reads" />
        </div>
      </div>
    </>
  );
}

/** A frame's root: the head passed in, the shared body under it. */
export function EditorFrame({ head, listing }: { head: ReactNode; listing: HeaderListing }) {
  return (
    <div className="editor">
      {head}
      <EditorBody listing={listing} />
    </div>
  );
}
