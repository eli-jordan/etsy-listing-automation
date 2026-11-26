import { useEffect, useState } from "react";
import { assignKind, getColourReport } from "../api/calibrator";
import type { ColourReportRow, TemplateKind } from "../types";

/** A takeover rather than an inspector field: kind decides the whole shape of
 * template.yaml, so every other control is meaningless until it is answered. */

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
  const [chosen, setChosen] = useState<TemplateKind | null>(null);
  const [report, setReport] = useState<ColourReportRow[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    getColourReport(templateName)
      .then(setReport)
      .catch(() => setReport([]));
  }, [templateName]);

  // One photo cannot be a colour set: "one photo per colour" over a single
  // file means a matrix of one, which is what `single` already is -- and
  // accepting it names the colour after the filename, so `photo.png` became a
  // garment colour called "photo". So the option is off for one photo, and
  // the default follows the count: several photos read as a colour set, one
  // reads as a single garment.
  const photos = report.length;
  const colourMatrixDisabled = photos === 1;
  const fallback: TemplateKind = colourMatrixDisabled ? "single" : "colour-matrix";
  // Falls back whenever the choice isn't (or is no longer) available -- which
  // covers picking colour-matrix before the report landed and learning
  // afterwards that there is only one photo.
  const kind: TemplateKind =
    chosen && !(colourMatrixDisabled && chosen === "colour-matrix") ? chosen : fallback;

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
        {KINDS.map((option) => {
          const disabled = option.kind === "colour-matrix" && colourMatrixDisabled;
          return (
            <label
              key={option.kind}
              className={`kind-picker__option${
                kind === option.kind ? " kind-picker__option--active" : ""
              }${disabled ? " kind-picker__option--disabled" : ""}`}
            >
              <input
                type="radio"
                name="template-kind"
                value={option.kind}
                checked={kind === option.kind}
                disabled={disabled}
                onChange={() => setChosen(option.kind)}
              />
              <span className="kind-picker__label">{option.label}</span>
              <span className="kind-picker__blurb">
                {disabled ? "needs more than one photo" : option.blurb}
              </span>
            </label>
          );
        })}
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
                    row.clean
                      ? "kind-picker__colour"
                      : "kind-picker__colour kind-picker__colour--warn"
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
          <p className="kind-picker__note">
            The filename is the colour; there is no mapping to set.
          </p>
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
