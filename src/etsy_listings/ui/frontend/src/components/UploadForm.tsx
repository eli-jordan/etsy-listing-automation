import { useState } from "react";
import { uploadTemplate } from "../api/calibrator";
import type { TemplateKind } from "../types";

interface Props {
  onUploaded: (name: string) => void;
}

const KINDS: { value: TemplateKind; label: string }[] = [
  { value: "colour-matrix", label: "Colour set (one photo per colour)" },
  { value: "multiple", label: "Chart (several garments in one photo)" },
  { value: "single", label: "Single shot (one photo, one garment)" },
];

/** Kind is chosen up front -- it decides the upload widget (colour-matrix:
 * several files, named by colour; multiple/single: exactly one photo) and
 * the starting template.yaml shape. */
export function UploadForm({ onUploaded }: Props) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<TemplateKind>("colour-matrix");
  const [status, setStatus] = useState("");

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0 || !name) return;
    try {
      await uploadTemplate(name, kind, Array.from(files));
      setStatus("uploaded");
      onUploaded(name);
    } catch {
      setStatus("upload failed");
    }
  }

  return (
    <fieldset className="upload-form">
      <legend>New template</legend>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="flat-lay-02" />
      </label>
      <label>
        Kind
        <select value={kind} onChange={(e) => setKind(e.target.value as TemplateKind)}>
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {kind === "colour-matrix" ? "Photos (one per colour)" : "Photo"}
        <input
          type="file"
          accept="image/png"
          multiple={kind === "colour-matrix"}
          onChange={(e) => handleFiles(e.target.files)}
        />
      </label>
      <p role="status">{status}</p>
    </fieldset>
  );
}
