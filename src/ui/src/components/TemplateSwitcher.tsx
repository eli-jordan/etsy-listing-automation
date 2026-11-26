import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CaretLeftIcon } from "@phosphor-icons/react/dist/csr/CaretLeft";
import { CaretRightIcon } from "@phosphor-icons/react/dist/csr/CaretRight";
import { type ReactNode, useId, useRef, useState } from "react";
import { templateThumbnailUrl } from "../api/calibrator";
import type { TemplateRename } from "../hooks/useTemplateRename";
import { PhoneSheet } from "../phone/PhoneSheet";
import { usePager } from "../phone/usePager";
import { stepPosition } from "./templateStep";

/** Swipes on the header only: on the photo a finger drags the box's corners. */

/** One button between two arrows: followed 1:1 it would slide over them. */
const DRAG_FOLLOW = 0.35;

interface SwitcherProps {
  names: readonly string[];
  selected: string;
  onSelect: (name: string) => void;
  onOpen: () => void;
  statusChip: ReactNode;
  contentsAndSaveState: ReactNode;
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

export function TemplateSwitcher({
  names,
  selected,
  onSelect,
  onOpen,
  statusChip,
  contentsAndSaveState,
}: SwitcherProps) {
  const zone = useRef<HTMLDivElement>(null);
  const current = useRef<HTMLButtonElement>(null);
  const { previous, next } = usePager(zone, {
    items: names,
    current: selected,
    onPick: onSelect,
    moves: current,
    follow: DRAG_FOLLOW,
  });

  return (
    <div ref={zone} className="tswitch">
      <button
        type="button"
        className="tswitch__step"
        aria-label="Previous template"
        disabled={!previous}
        onClick={() => {
          if (previous) onSelect(previous);
        }}
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
            {statusChip}
            <span className="tswitch__position">{stepPosition(names, selected)}</span>
          </span>
        </span>
      </button>
      <button
        type="button"
        className="tswitch__step"
        aria-label="Next template"
        disabled={!next}
        onClick={() => {
          if (next) onSelect(next);
        }}
      >
        <CaretRightIcon aria-hidden="true" />
      </button>
      <div className="tswitch__status">{contentsAndSaveState}</div>
    </div>
  );
}

/** A finger cannot reliably double-click the name, as the desktop renames. */
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
  children: ReactNode;
}

/** Every template, as a bottom sheet over the page. A `PhoneSheet`, so it
 * sits on the body, where the calibrator's own narrow-width rules (which
 * fold the rail away) do not reach the copy of the rail inside it. */
export function TemplateSheet({ selected, rename, onClose, children }: SheetProps) {
  return (
    <PhoneSheet title="Templates" onClose={onClose} className="tsheet__dialog">
      <RenameRow key={selected} name={selected} rename={rename} />
      {children}
    </PhoneSheet>
  );
}
