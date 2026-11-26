import { useEffect, useState } from "react";
import { listDesigns, uploadDesign } from "../api/calibrator";
import type { DesignSummary } from "../types";

interface Props {
  compact?: boolean;
  value: string;
  onChange: (id: string) => void;
}

export function TestDesignPicker({ value, onChange, compact = false }: Props) {
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
        // Spliced in, not re-fetched: a round trip would leave the new design briefly
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
    <section className={compact ? "design-picker design-picker--compact" : "design-picker"}>
      <h3 className="design-picker__heading">{compact ? "Design" : "Test design"}</h3>

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

      <label className="design-picker__upload" title="Upload a PNG design">
        <span>{compact ? "+ Upload" : "＋ Upload a PNG…"}</span>
        <input type="file" accept="image/png" onChange={(e) => handleUpload(e.target.files?.[0])} />
      </label>

      <p className="design-picker__status" role="status">
        {status}
      </p>
    </section>
  );
}
