import type { ReactNode } from "react";
import type { Positioning } from "./usePositioning";

export function PositionControls({
  positioning,
  children,
}: {
  positioning: Positioning;
  children?: ReactNode;
}) {
  const unavailable = positioning.waiting && !positioning.on;
  return (
    <span className="tp-controls">
      {positioning.fit !== null && (
        <button
          type="button"
          className="btn-like btn-like--primary btn-sm"
          onClick={positioning.fit}
        >
          Fit within limits
        </button>
      )}
      {!positioning.on && children}
      {positioning.reset !== null && (
        <button
          type="button"
          className="tp-link"
          disabled={positioning.reset.run === null}
          onClick={positioning.reset.run ?? undefined}
        >
          {positioning.reset.label}
        </button>
      )}
      <label className="tp-switch">
        <span>Adjust position</span>
        <button
          type="button"
          role="switch"
          aria-checked={positioning.on}
          aria-disabled={unavailable}
          aria-label="Adjust position"
          className={switchClass(positioning.on, unavailable)}
          onClick={positioning.toggle}
        >
          <span className="switch__knob" />
        </button>
      </label>
    </span>
  );
}

function switchClass(on: boolean, unavailable: boolean): string {
  if (on) return "switch switch--on";
  return unavailable ? "switch tp-switch--unavailable" : "switch";
}

export function PositionNote({ note }: { note: Positioning["note"] }) {
  if (note === null) return null;
  return <span className={note.warn ? "tp-note tp-note--warn" : "tp-note"}>{note.text}</span>;
}

export function PositionGlyph() {
  return (
    <svg
      width={12}
      height={12}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3" />
    </svg>
  );
}
