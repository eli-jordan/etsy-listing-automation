import type { ReactNode } from "react";
import type { Positioning } from "./usePositioning";

/**
 * The preview foot's right-hand group in Position mode: Fit within limits,
 * the Reset link and the Adjust position switch (`_panes.tsx`'s `Foot` and
 * `PositionSwitch` in the prototype). `children` is the pane's own action
 * (Add / Remove from listing), shown only while the switch is off so the
 * group matches the approved frames while adjusting.
 */
export function PositionControls({
  positioning,
  children,
}: {
  positioning: Positioning;
  children?: ReactNode;
}) {
  // Still clickable: the click is what says why, and what starts the wait's end.
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
        <button type="button" className="tp-link" onClick={positioning.reset.run}>
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

/** The foot's note line: the colour-matrix scope, the placement hint, or
 * why a stored position is refused. */
export function PositionNote({ note }: { note: Positioning["note"] }) {
  if (note === null) return null;
  return <span className={note.warn ? "tp-note tp-note--warn" : "tp-note"}>{note.text}</span>;
}

/** Four-way move arrows (the prototype's `PositionGlyph`), for the reel badge. */
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
