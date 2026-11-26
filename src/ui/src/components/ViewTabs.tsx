export type View = "calibrate" | "preview";

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
