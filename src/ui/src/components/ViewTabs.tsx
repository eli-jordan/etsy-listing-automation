export type View = "calibrate" | "preview";

/**
 * Calibrate / Preview, the same two views for every template kind.
 *
 * It began as colour-matrix's "Preview all N" and belonged to that kind
 * because only a colour set had several outputs to look at. That was the wrong
 * reason: what the tab is really for is *judging at full size*, which every
 * kind needs now that the editing canvas deliberately renders small. So the
 * label lost its count -- one preview or twelve, it is the same view -- and
 * the control moved here rather than being written out three times.
 */
export function ViewTabs({ value, onChange }: { value: View; onChange: (view: View) => void }) {
  return (
    <div className="seg" role="tablist" aria-label="View">
      {(["calibrate", "preview"] as const).map((view) => (
        <button
          key={view}
          type="button"
          role="tab"
          aria-selected={value === view}
          className={`seg-opt${value === view ? " seg-opt--on" : ""}`}
          onClick={() => onChange(view)}
        >
          {view === "calibrate" ? "Calibrate" : "Preview"}
        </button>
      ))}
    </div>
  );
}
