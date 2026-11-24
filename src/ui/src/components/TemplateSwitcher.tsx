import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CaretLeftIcon } from "@phosphor-icons/react/dist/csr/CaretLeft";
import { CaretRightIcon } from "@phosphor-icons/react/dist/csr/CaretRight";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { templateThumbnailUrl } from "../api/calibrator";
import type { TemplateRename } from "../hooks/useTemplateRename";
import { SheetGrabber } from "../phone/SheetGrabber";
import { useSwipe } from "../phone/useSwipe";
import { adjacentTemplate, stepPosition, type StepDirection } from "./templateStep";

/**
 * The calibrator's header on a phone, where the template rail has no room:
 * the open template's name is the button that opens every template in a
 * bottom sheet, with an arrow either side to step to its neighbours. A
 * left/right swipe on the header steps too -- on the header only, never on
 * the photo, where a finger drags the box's corners.
 *
 * Rendered only while the phone layout shows (App asks `useIsPhone`), so the
 * desktop header is untouched.
 */

/** How far the name follows a finger, as a share of the finger's travel: it
 * gives under the thumb without ever looking like it is leaving. */
const DRAG_FOLLOW = 0.35;

interface SwitcherProps {
  names: readonly string[];
  selected: string;
  onSelect: (name: string) => void;
  onOpen: () => void;
  /** The status chip beside the name. */
  chip: ReactNode;
  /** What the template holds, and whether it is saved. */
  meta: ReactNode;
}

function Thumb({ name }: { name: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (failed === name) return <span className="tswitch__thumb tswitch__thumb--empty" />;
  return (
    <img
      className="tswitch__thumb"
      src={templateThumbnailUrl(name)}
      alt=""
      onError={() => setFailed(name)}
    />
  );
}

export function TemplateSwitcher({ names, selected, onSelect, onOpen, chip, meta }: SwitcherProps) {
  const zone = useRef<HTMLDivElement>(null);
  const current = useRef<HTMLButtonElement>(null);
  const previous = adjacentTemplate(names, selected, "previous");
  const next = adjacentTemplate(names, selected, "next");

  const follow = (offset: number) => {
    const button = current.current;
    if (!button) return;
    button.style.transition = offset ? "none" : "";
    button.style.transform = offset ? `translateX(${offset * DRAG_FOLLOW}px)` : "";
  };
  const step = (direction: StepDirection) => {
    const target = direction === "next" ? next : previous;
    if (target) onSelect(target);
  };

  useSwipe(zone, {
    axis: "x",
    onDrag: follow,
    onSwipe: (direction) => {
      follow(0);
      // Swiping left brings the next template in from the right.
      if (direction === "left") step("next");
      if (direction === "right") step("previous");
    },
  });

  return (
    <div ref={zone} className="tswitch">
      <button
        type="button"
        className="tswitch__step"
        aria-label="Previous template"
        disabled={!previous}
        onClick={() => step("previous")}
      >
        <CaretLeftIcon aria-hidden="true" />
      </button>
      <button
        ref={current}
        type="button"
        className="tswitch__current"
        aria-haspopup="dialog"
        aria-label={`Template ${selected}, ${stepPosition(names, selected) ?? ""}. Choose another`}
        onClick={onOpen}
      >
        <Thumb name={selected} />
        <span className="tswitch__text">
          <span className="tswitch__name-row">
            <span className="tswitch__name">{selected}</span>
            <CaretDownIcon className="tswitch__caret" aria-hidden="true" />
          </span>
          <span className="tswitch__meta">
            {chip}
            <span className="tswitch__position">{stepPosition(names, selected)}</span>
          </span>
        </span>
      </button>
      <button
        type="button"
        className="tswitch__step"
        aria-label="Next template"
        disabled={!next}
        onClick={() => step("next")}
      >
        <CaretRightIcon aria-hidden="true" />
      </button>
      <div className="tswitch__status">{meta}</div>
    </div>
  );
}

/** Renaming the open template from the sheet. The desktop renames by
 * double-clicking the name, which a finger cannot do reliably. */
function RenameRow({ name, rename }: { name: string; rename: TemplateRename }) {
  const [text, setText] = useState<string | null>(null);
  const inputId = useId();
  if (text === null) {
    return (
      <div className="tsheet__current">
        <span className="tsheet__current-name">{name}</span>
        <button type="button" className="btn btn-secondary" onClick={() => setText(name)}>
          Rename
        </button>
      </div>
    );
  }
  const trimmed = text.trim();
  const refused = rename.refusal !== null && rename.refusal.name === trimmed;
  return (
    <form
      className="tsheet__rename"
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmed === "" || trimmed === name) setText(null);
        else void rename.commit(trimmed);
      }}
    >
      <label htmlFor={inputId} className="tsheet__rename-label">
        Template name
      </label>
      <input
        id={inputId}
        className="input"
        value={text}
        readOnly={rename.busy}
        autoFocus
        onChange={(event) => setText(event.target.value)}
      />
      {refused && (
        <p className="tsheet__rename-error" role="alert">
          {rename.refusal?.message}
        </p>
      )}
      <div className="tsheet__rename-actions">
        <button type="button" className="btn btn-ghost" onClick={() => setText(null)}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={rename.busy}>
          {rename.busy ? "Renaming…" : "Save name"}
        </button>
      </div>
    </form>
  );
}

interface SheetProps {
  selected: string;
  rename: TemplateRename;
  onClose: () => void;
  /** The template rail, which picks and closes. */
  children: ReactNode;
}

/** Every template, as a bottom sheet over the page. Portalled to the body so
 * the calibrator's own narrow-width rules (which fold the rail away) do not
 * reach the copy of the rail inside it. */
export function TemplateSheet({ selected, rename, onClose, children }: SheetProps) {
  const sheet = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="modal-root tsheet" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />
      <div ref={sheet} className="modal-dialog tsheet__dialog">
        <SheetGrabber sheetRef={sheet} onDismiss={onClose} />
        <div className="tsheet__head">
          <h2 id={titleId} className="tsheet__title">
            Templates
          </h2>
          <button type="button" className="btn btn-ghost tsheet__close" onClick={onClose}>
            Done
          </button>
        </div>
        <RenameRow key={selected} name={selected} rename={rename} />
        {children}
      </div>
    </div>,
    document.body,
  );
}
