import { useEffect, useState } from "react";
import { assignKind, getColourReport } from "../api/calibrator";
import type { ColourReportRow, TemplateKind } from "../types";

/**
 * The first calibration step: what kind of template is this?
 *
 * Wireframe 2a makes this a takeover rather than a field in the inspector --
 * "the workspace is replaced by a single choice, so nothing else can be
 * touched yet". That is not decoration: kind decides the whole shape of
 * template.yaml (A11), so every other control on the page is either
 * meaningless or actively wrong until it is answered.
 *
 * For a colour-matrix candidate it also shows what colour each filename will
 * be taken as. PRD 7a makes the filename the source of truth, so this reports
 * the rule rather than offering a mapping to edit -- the fix for a bad name is
 * to rename the file.
 */

const KINDS: { kind: TemplateKind; label: string; blurb: string }[] = [
  { kind: "colour-matrix", label: "Colour Matrix", blurb: "one photo per colour" },
  { kind: "multiple", label: "Multiple", blurb: "many garments, one photo" },
  { kind: "single", label: "Single", blurb: "one photo, one garment" },
];

interface Props {
  templateName: string;
  onAssigned: () => void;
}

export function KindPicker({ templateName, onAssigned }: Props) {
  const [kind, setKind] = useState<TemplateKind>("colour-matrix");
  const [report, setReport] = useState<ColourReportRow[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    // A failed report is not fatal: it only informs the colour-matrix choice,
    // and the kind still has to be assignable without it.
    getColourReport(templateName)
      .then(setReport)
      .catch(() => setReport([]));
  }, [templateName]);

  const messy = report.filter((row) => !row.clean);

  function handleAssign(): void {
    setStatus("saving…");
    assignKind(templateName, kind)
      .then(() => {
        setStatus("");
        onAssigned();
      })
      .catch(() => setStatus("could not set the kind"));
  }

  return (
    <section className="kind-picker">
      <h2 className="kind-picker__question">What kind of template is this?</h2>
      <p className="kind-picker__sub">
        {templateName} · {report.length || "no"} photo{report.length === 1 ? "" : "s"} · not
        calibrated
      </p>

      <div className="kind-picker__options">
        {KINDS.map((option) => (
          <label
            key={option.kind}
            className={`kind-picker__option${
              kind === option.kind ? " kind-picker__option--active" : ""
            }`}
          >
            <input
              type="radio"
              name="template-kind"
              value={option.kind}
              checked={kind === option.kind}
              onChange={() => setKind(option.kind)}
            />
            <span className="kind-picker__label">{option.label}</span>
            <span className="kind-picker__blurb">{option.blurb}</span>
          </label>
        ))}
      </div>

      {kind === "colour-matrix" && report.length > 0 && (
        <div className="kind-picker__report">
          <h3 className="kind-picker__report-heading">Colours read from filenames</h3>
          <ul className="kind-picker__files">
            {report.map((row) => (
              <li key={row.filename} className="kind-picker__file">
                <span className="kind-picker__filename">{row.filename}</span>
                <span
                  className={
                    row.clean ? "kind-picker__colour" : "kind-picker__colour kind-picker__colour--warn"
                  }
                >
                  {row.colour} {row.clean ? "✓" : "(will rename)"}
                </span>
              </li>
            ))}
          </ul>
          {messy.length > 0 && (
            <p className="kind-picker__warn">
              {`${messy.length} filename${messy.length === 1 ? " is" : "s are"} not a colour slug`}
              {" — rename to <colour>.png so the file on disk matches the colour it means."}
            </p>
          )}
          <p className="kind-picker__note">The filename is the colour; there is no mapping to set.</p>
        </div>
      )}

      <div className="kind-picker__actions">
        <span className="kind-picker__status" role="status">
          {status}
        </span>
        <button type="button" className="btn btn-primary" onClick={handleAssign}>
          Start calibrating →
        </button>
      </div>
    </section>
  );
}
