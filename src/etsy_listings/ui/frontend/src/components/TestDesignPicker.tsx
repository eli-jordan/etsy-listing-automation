import { useEffect, useState } from "react";
import { listDesigns, uploadDesign } from "../api/calibrator";
import type { DesignSummary } from "../types";

/**
 * Which artwork the live preview is rendered with (A19).
 *
 * Not part of `template.yaml` -- it is a way of looking at the template, not a
 * property of it, which is why it lives in component state and only ever
 * reaches the server as the preview request's `design` field.
 *
 * A native `<select>` with `<optgroup>`s rather than the wireframe's custom
 * radio menu: it is a single-choice list of short labels, which is exactly
 * what a select is for, and it comes with keyboard handling and a scroll
 * behaviour that a hand-rolled menu would have to reimplement.
 */

interface Props {
  value: string;
  onChange: (id: string) => void;
}

export function TestDesignPicker({ value, onChange }: Props) {
  const [designs, setDesigns] = useState<DesignSummary[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    listDesigns()
      .then(setDesigns)
      .catch(() => setStatus("could not load test designs"));
  }, []);

  const bundled = designs.filter((d) => d.source === "bundled");
  const uploads = designs.filter((d) => d.source === "upload");

  function handleUpload(file: File | undefined): void {
    if (!file) return;
    setStatus("uploading…");
    uploadDesign(file)
      .then((added) => {
        // Spliced in rather than re-fetched: the response already says what
        // was added, and a round trip would leave the new design briefly
        // unselectable in the list that just gained it.
        setDesigns((current) =>
          current.some((d) => d.id === added.id) ? current : [...current, added],
        );
        setStatus("");
        onChange(added.id);
      })
      .catch(() => setStatus("upload failed"));
  }

  return (
    <section className="design-picker">
      {/* The heading names the control, so the select carries the accessible
          name rather than a second visible label repeating it. */}
      <h3 className="design-picker__heading">Test design</h3>

      <select
        className="input design-picker__select"
        aria-label="Test design"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <optgroup label="Bundled">
          {bundled.map((d) => (
            <option key={d.id} value={d.id}>
              {d.label}
            </option>
          ))}
        </optgroup>
        {uploads.length > 0 && (
          <optgroup label="My uploads">
            {uploads.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </optgroup>
        )}
      </select>

      <label className="design-picker__upload">
        <span>＋ Upload a PNG…</span>
        <input type="file" accept="image/png" onChange={(e) => handleUpload(e.target.files?.[0])} />
      </label>

      <p className="design-picker__status" role="status">
        {status}
      </p>
    </section>
  );
}
